from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from types import MappingProxyType
from typing import Any

from strata.agent.context import Context
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy
from strata.tools.base import Tool

# 패턴 지시(harness prompt) — 고정 텍스트. 사용자 지시(Context.instructions) 뒤에 그대로 붙는다.
# 덮어쓰기는 `ReActStrategy(prompt=...)`, 끄기는 `prompt=''`, 하위 전략은 이 문자열 위에 자기 규칙을 이어 붙인다.
# 호출 시점에 변하는 설명(RLM의 변수 목록 등)은 여기가 아니라 environment()로 뒤에 붙는다.
REACT_PROMPT = """\
# How you work
You solve the task in a loop: think, optionally call tools, read the results, repeat. \
You may call several tools in one turn when they are independent.

## Using tools
- Call a tool only when it gives you something you do not already know or cannot compute reliably yourself.
- Tool results come back as observations in this conversation. Read them before acting again. \
Never invent, guess, or "remember" a tool result you did not actually receive.
- An observation like `Tool 'x' failed: ...` or `Tool 'x' not found. Available: [...]` is an error \
report, not a crash. Fix the arguments or pick another tool; do not repeat the identical failing call.
- Be economical: the number of turns is limited. Batch independent calls, avoid redundant lookups, \
and stop as soon as you can answer.

## Finishing
- When you have the final answer, reply in plain text **without calling any tool**. A reply with no \
tool call ends the loop, so do not send a text-only reply until you are done.
- If you cannot fully finish (missing tool, repeated failures, limits reached), say what you did, \
what you found, and what is still missing — a partial answer beats a fabricated one."""


def _observation_text(observation: Any) -> str:
    """Tool 결과를 모델에게 보여줄 문자열로. 문자열은 그대로, 나머지는 JSON."""
    if isinstance(observation, str):
        return observation
    return json.dumps(observation, ensure_ascii=False, default=str)


class ReActStrategy(Strategy):
    """Tool을 반복 사용하며 문제를 해결하는 최소 tool calling loop.

    "Thought"는 네이티브 tool calling 모델의 response.text에 암묵적으로 담긴다.
    루프 상한(max_iterations)·토큰 예산은 이 클래스가 아니라 runtime.generate가 강제한다 —
    한도 초과 시 BudgetExceeded가 올라오고 Runtime이 budget_exceeded 결과로 변환한다.
    하위 전략(Recursive, RLM)은 default_tools로 tool을 추가하고 prompt/environment로 지시를 덧붙인다.
    """

    description = 'Solve the task directly by calling tools in a loop. The general-purpose default.'

    # 전략이 기본 제공하는 tool. registry에 같은 이름이 있으면 registry가 이긴다 — 사용자 교체점(샌드박스 python 등)
    default_tools: tuple[Tool, ...] = ()
    # 패턴 지시(고정 텍스트). 하위 전략이 교체하고 사용자가 prompt= 인자로 덮어쓴다. ''이면 생략.
    prompt: str = REACT_PROMPT
    # 이 전략의 모든 generate에 실리는 샘플링 파라미터(temperature 등). 코어는 해석하지 않고 Provider까지
    # 그대로 전달한다 — Provider 기본값보다 우선. 클래스 기본값은 읽기 전용(super().__init__ 없는 서브클래스 보호).
    model_params: Mapping[str, Any] = MappingProxyType({})

    def __init__(
        self,
        *,
        prompt: str | None = None,
        model_params: dict[str, Any] | None = None,
        **limits: Any,
    ):
        # limits는 RuntimeConfig 필드 이름 — ReActStrategy(max_iterations=10) 처럼 전략에 붙여 준다.
        # 재귀 계열은 max_depth/max_children을 같은 자리에서 받는다 (ADR-0014).
        super().__init__(**limits)
        if prompt is not None:
            self.prompt = prompt
        if model_params:
            self.model_params = dict(model_params)

    def tools(self, runtime: Runtime) -> list[Tool]:
        """모델에게 광고할 tool: registry 전체 + default_tools(이름 충돌 시 registry 우선)."""
        return [*runtime.tools.values(), *(t for t in self.default_tools if t.name not in runtime.tools)]

    def environment(self, context: Context) -> str | None:
        """호출 시점에 변하는 상태 설명 — RLM의 변수 목록, Reflection의 이전 초안 등. 기본은 없음."""
        return None

    def instructions(self, context: Context, runtime: Runtime) -> str | None:
        """이번 호출의 system = 사용자 지시(원본, child가 상속) + 패턴 지시 + 현재 상태. 모두 없으면 None."""
        parts = (context.instructions, self.prompt, self.environment(context))
        return '\n\n'.join(p for p in parts if p) or None

    async def execute(self, context: Context, runtime: Runtime) -> AgentResult:
        tools = self.tools(runtime)
        by_name = {tool.name: tool for tool in tools}
        while True:
            response = await runtime.generate(
                context,
                tools=tools,
                instructions=self.instructions(context, runtime),
                **self.model_params,
            )
            context.messages.append({
                'role': 'assistant',
                'content': response.text,
                # ToolCall 객체가 아니라 dict로 — Context.messages는 순수 JSON 데이터여야 한다.
                # 앱이 이걸 저장했다 history로 되돌려 준다 (ADR-0010).
                'tool_calls': [asdict(call) for call in response.tool_calls],
            })
            if not response.tool_calls:
                return AgentResult(result=response.text)

            # ponytail: 순차 실행 — 병렬 child가 필요해지면 asyncio.gather로 전환
            for call in response.tool_calls:
                observation = await runtime.execute_tool(call.name, call.arguments, context, tools=by_name)
                context.messages.append({
                    'role': 'tool',
                    'name': call.name,
                    'tool_call_id': call.id,
                    'content': _observation_text(observation),
                })
