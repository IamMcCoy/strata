from __future__ import annotations

from strata.agent.context import Context
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult


class Agent:
    """Provider + Strategy + Tools + Memory의 조합 단위.

    특정 패턴의 실행 로직을 갖지 않는다 — 실행은 Strategy에 위임한다 (ADR-0003).
    runtime 미지정 시 새 run의 Runtime을 생성한다(root agent의 경우).
    child agent는 직접 만들지 않고 runtime.spawn_agent가 parent의 Runtime을
    공유시켜 생성한다 (ADR-0006).
    """

    def __init__(self, provider, strategy, tools=None, memory=None, runtime=None):
        self.provider = provider
        self.strategy = strategy
        self.tools = tools or []
        self.memory = memory
        self.runtime = runtime or Runtime(
            provider=provider,
            tools=self.tools,
            memory=memory,
        )

    async def run(self, task: str) -> AgentResult:
        # ponytail: Memory retrieve → Context 주입은 Phase 4에서 이 지점에 추가
        context = Context(metadata={'task': task})
        return await self.strategy.execute(context, self.runtime)
