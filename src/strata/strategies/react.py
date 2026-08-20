from __future__ import annotations

import json
from typing import Any

from strata.agent.context import Context
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy
from strata.tools.base import Tool


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
    하위 전략(Recursive, RLM)은 default_tools로 tool을 추가하고 instructions()로 지시를 덧붙인다.
    """

    # 전략이 기본 제공하는 tool. registry에 같은 이름이 있으면 registry가 이긴다 — 사용자 교체점(샌드박스 python 등)
    default_tools: tuple[Tool, ...] = ()

    def tools(self, runtime: Runtime) -> list[Tool]:
        """모델에게 광고할 tool: registry 전체 + default_tools(이름 충돌 시 registry 우선)."""
        return [*runtime.tools.values(), *(t for t in self.default_tools if t.name not in runtime.tools)]

    def instructions(self, context: Context, runtime: Runtime) -> str | None:
        """이번 호출의 system 지시. 기본은 context의 것 그대로."""
        return context.instructions

    async def execute(self, context: Context, runtime: Runtime) -> AgentResult:
        tools = self.tools(runtime)
        by_name = {tool.name: tool for tool in tools}
        while True:
            response = await runtime.generate(
                context,
                tools=tools,
                instructions=self.instructions(context, runtime),
            )
            context.messages.append({
                'role': 'assistant',
                'content': response.text,
                'tool_calls': response.tool_calls,
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
