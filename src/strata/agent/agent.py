from __future__ import annotations

import asyncio
from typing import Any

from strata.agent.context import Context
from strata.runtime.config import RuntimeConfig
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult


class Agent:
    """Provider + Strategy + Tools + Memory (+ instructions)의 조합 단위.

    특정 패턴의 실행 로직을 갖지 않는다 — 실행은 Strategy에 위임한다 (ADR-0003).
    Runtime은 run당 하나 — run()이 매번 새로 만들고 child agent는 runtime.spawn_agent가
    그 인스턴스를 공유시켜 생성한다 (ADR-0006). 마지막 run의 Runtime은 `agent.runtime`으로
    조회한다(Execution Tree·usage).
    """

    def __init__(
        self,
        provider,
        strategy,
        tools=None,
        memory=None,
        instructions: str | None = None,
        config: RuntimeConfig | None = None,
    ):
        self.provider = provider
        self.strategy = strategy
        self.tools = tools or []
        self.memory = memory
        self.instructions = instructions
        self.config = config or RuntimeConfig()
        self.runtime: Runtime | None = None  # 마지막 run의 Runtime

    async def run(self, task: str, context: Any = None) -> AgentResult:
        """유일한 진입점. context는 거대 입력 — messages가 아니라 variables['context']로 들어간다."""
        runtime = self.runtime = Runtime(
            provider=self.provider, tools=self.tools, memory=self.memory, config=self.config,
        )
        runtime.default_strategy = self.strategy  # spawn 시 strategy 미지정이면 상속 (ADR-0006)
        # ponytail: Memory retrieve → Context 주입은 Phase 4에서 이 지점에 추가
        node = runtime.execution.open(task)
        ctx = Context(
            messages=[{'role': 'user', 'content': task}],
            instructions=self.instructions,
            variables={'context': context} if context is not None else {},
            metadata={'task': task, 'execution_id': node.id},
        )
        try:
            async with asyncio.timeout(self.config.timeout):  # None이면 무제한
                result = await runtime.run_strategy(self.strategy, ctx)
        except TimeoutError:
            result = AgentResult(
                status='budget_exceeded',
                result=ctx.last_assistant_text(),
                metadata={'reason': 'timeout', 'limit': self.config.timeout},
            )
        except BaseException:
            # root의 프로그래밍 오류는 숨기지 않는다 — tree에만 failed로 남기고 전파
            runtime.execution.close(node.id, AgentResult(status='failed'))
            raise
        runtime.execution.close(node.id, result)
        return result
