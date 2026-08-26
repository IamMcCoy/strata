from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from strata.agent.context import Context
from strata.providers.base import ModelResponse
from strata.runtime.config import RuntimeConfig
from strata.runtime.execution import ExecutionManager
from strata.runtime.ids import new_run_id
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy
from strata.tools.base import Tool
from strata.tools.base import ToolEnv

USAGE_KEYS = ('input_tokens', 'output_tokens', 'total_tokens')


class BudgetExceeded(Exception):
    """Runtime이 한도 초과를 Strategy에 알리는 내부 신호.

    Strategy가 잡지 않아도 Agent.run / spawn_agent가 AgentResult(status='budget_exceeded')로
    변환한다 — 공개 계약은 여전히 예외가 아니라 결과다.
    """

    def __init__(self, reason: str, limit: Any):
        super().__init__(f'{reason} limit exceeded: {limit}')
        self.reason = reason
        self.limit = limit


class Cancelled(Exception):
    """Runtime이 협조적 취소를 Strategy에 알리는 내부 신호 (ADR-0011).

    BudgetExceeded와 같은 길을 쓴다 — Strategy가 몰라도 run_strategy가
    AgentResult(status='cancelled')로 변환한다. 지금까지의 답은 버리지 않는다.
    """

    def __init__(self, reason: str | None = None):
        super().__init__(reason or 'cancelled')
        self.reason = reason


class Runtime:
    """Agent 실행의 공통 환경: registry, generate/execute_tool/spawn primitive, 실행 한도.

    인스턴스는 run당 하나 — token usage, Execution Tree 등 run 전역 상태를
    담으며 child agent는 spawn을 통해 이를 공유한다 (ADR-0006).
    Strategy는 이 클래스가 제공하는 primitive를 통해서만
    Provider/Tool/Memory/Child Agent에 접근한다 — 한도·집계·이벤트가 전부 여기서 일어난다.
    """

    def __init__(self, provider=None, tools=None, memory=None, config=None):
        # run 하나의 유일한 이름. child는 spawn에서 이 Runtime을 공유하므로 run_id도 공유한다
        # — 재귀 전체가 하나의 run이다 (ADR-0011).
        self.run_id: str = new_run_id()
        self.cancelled: str | None = None  # 협조적 취소 플래그 — cancel()이 세운다
        self.provider = provider
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.memory = memory
        self.config = config or RuntimeConfig()
        self.execution = ExecutionManager()
        self.usage: dict[str, int] = dict.fromkeys(USAGE_KEYS, 0)  # run 전체 누적
        # spawn 시 strategy 미지정이면 이 값을 상속 — root Agent가 설정 (ADR-0006)
        self.default_strategy: Strategy | None = None

    def cancel(self, reason: str = 'cancelled') -> None:
        """협조적 취소를 요청한다. 다음 primitive 경계에서 멈추고 지금까지의 답을 반환한다.

        asyncio.Task.cancel()과 다르다: 그쪽은 즉시 끊어 부분 결과를 버리고,
        이쪽은 이미 쓴 토큰을 살린다. 실행 중인 tool은 끝까지 기다린다.
        """
        self.cancelled = reason

    def _check_stop(self) -> None:
        """취소·토큰 예산 검사. generate와 spawn_agent가 공유하는 관문."""
        if self.cancelled:
            raise Cancelled(self.cancelled)
        budget = self.config.token_budget
        if budget is not None and self.usage['total_tokens'] >= budget:
            raise BudgetExceeded('token_budget', budget)

    # ---- primitive 1: LLM 호출 ---------------------------------------------------

    async def generate(
        self,
        context: Context,
        tools: list[Tool] | None = None,
        instructions: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Provider 호출의 유일한 경로. system 메시지 조립 + 한도 검사 + usage 누적.

        instructions를 넘기면 이번 호출에 한해 context.instructions 대신 쓴다
        (Strategy가 환경 설명 등을 덧붙이는 용도).
        kwargs는 모델 파라미터(temperature 등) — Provider 기본값 위에 얹는다. 우선순위는 여기 한 줄뿐이다:
        호출(Strategy) 값 > provider.model_params.
        """
        node = self.execution.nodes.get(context.metadata.get('execution_id'))
        if node is not None:
            node.iterations += 1
            if node.iterations > self.config.max_iterations:
                raise BudgetExceeded('max_iterations', self.config.max_iterations)
        # ponytail: 취소는 generate와 spawn_agent에서만 본다 — 루프의 심장이라 매 반복 지난다.
        # 실행 중인 tool은 끝까지 간다(취소가 최대 tool 하나만큼 늦는다). 더 빨라야 하면 execute_tool에도 단다.
        self._check_stop()

        system = instructions if instructions is not None else context.instructions
        messages = context.messages
        if system:
            messages = [{'role': 'system', 'content': system}, *messages]

        response = await self.provider.generate(messages, tools=tools, **{**self.provider.model_params, **kwargs})
        for key in USAGE_KEYS:
            self.usage[key] += int(response.usage.get(key, 0) or 0)
        return response

    # ---- primitive 2: Tool 실행 ---------------------------------------------------

    async def execute_tool(
        self,
        name: str,
        arguments: dict,
        context: Context,
        tools: Mapping[str, Tool] | None = None,
    ) -> Any:
        """Tool 호출의 유일한 경로. 관찰(observation)로 쓸 값을 반환한다.

        tools 미지정 시 registry에서 찾는다. Strategy가 자체 tool(spawn_agent, python 등)을
        함께 광고했다면 그 매핑을 넘긴다. 알 수 없는 tool·실행 예외는 예외 전파가 아니라
        관찰 문자열로 돌려 모델이 회복하게 한다 — run은 모델 실수로 죽지 않는다.
        """
        registry = tools if tools is not None else self.tools
        tool = registry.get(name)
        if tool is None:
            return f"Tool '{name}' not found. Available: {sorted(registry)}"
        try:
            return await tool.execute(ToolEnv(context=context, runtime=self), **arguments)
        except BudgetExceeded:
            raise
        except Exception as exc:
            return f'Tool {name!r} failed: {exc!r}'

    # ---- primitive 3: Child Agent -------------------------------------------------

    async def spawn_agent(
        self,
        task: str,
        parent_context: Context,
        *,
        context: Any = None,
        instructions: str | None = None,
        strategy: Strategy | None = None,
        provider: Any = None,
    ) -> AgentResult:
        """Child Agent 생성·실행 (ADR-0004/0006). RLM의 llm_query(sub_context, instruction)에 대응.

        - context: child의 `variables['context']`에 들어갈 sub-context (거대 입력의 조각).
          parent의 variables 전체는 넘기지 않는다 — 격리가 기본.
        - instructions 미지정 시 parent의 instructions를 상속한다.
        - strategy/provider 미지정 시 parent 것을 상속한다.
        한도 초과·child 예외는 예외 전파가 아니라 결과 계약(AgentResult)으로 반환한다.
        """
        parent = self.execution.nodes.get(parent_context.metadata.get('execution_id'))
        if parent is None:
            raise ValueError('parent_context is not attached to an execution node')
        # 취소는 계약이 아니라 신호로 올린다 — depth/children 초과는 "이 가지만 못 간다"지만
        # 취소는 "run 전체를 멈춰라"이기 때문이다. run_strategy가 계약으로 변환한다.
        self._check_stop()

        if parent.depth + 1 > self.config.max_depth:
            return AgentResult(
                status='budget_exceeded',
                metadata={'reason': 'max_depth', 'limit': self.config.max_depth},
            )
        if len(parent.children) >= self.config.max_children:
            return AgentResult(
                status='budget_exceeded',
                metadata={'reason': 'max_children', 'limit': self.config.max_children},
            )

        child_strategy = strategy or self.default_strategy
        if child_strategy is None:
            return AgentResult(status='failed', result='no strategy to inherit for child agent')

        node = self.execution.open(task, parent_id=parent.id)
        child_context = Context(
            messages=[{'role': 'user', 'content': task}],
            instructions=instructions if instructions is not None else parent_context.instructions,
            variables={'context': context} if context is not None else {},
            metadata={'task': task, 'execution_id': node.id},
        )
        child_runtime = self
        if provider is not None:
            # 얕은 복사 — execution/config/tools/memory/usage는 공유, provider만 교체
            child_runtime = copy.copy(self)
            child_runtime.provider = provider

        try:
            result = await self.run_strategy(child_strategy, child_context, child_runtime)
        except Exception as exc:  # child 실패가 parent를 죽이지 않는다 — 계약으로 변환
            result = AgentResult(status='failed', result=repr(exc))
        self.execution.close(node.id, result)
        return result

    # ---- 공통 실행 경로 ---------------------------------------------------------------

    async def run_strategy(self, strategy: Strategy, context: Context, runtime: Runtime | None = None) -> AgentResult:
        """Strategy 실행 + 한도 초과를 결과 계약으로 변환. Agent.run과 spawn_agent가 공유한다."""
        try:
            return await strategy.execute(context, runtime or self)
        except Cancelled as exc:
            # 지금까지의 답을 버리지 않는다 — 협조적 취소의 존재 이유다
            return AgentResult(
                status='cancelled',
                result=context.last_assistant_text(),
                metadata={'reason': exc.reason},
            )
        except BudgetExceeded as exc:
            return AgentResult(
                status='budget_exceeded',
                result=context.last_assistant_text(),
                metadata={'reason': exc.reason, 'limit': exc.limit},
            )
