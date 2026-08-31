from __future__ import annotations

import asyncio
import logging
from typing import Any

from strata.agent.context import Context
from strata.runtime.config import resolve_limits
from strata.runtime.config import RuntimeConfig
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult

logger = logging.getLogger(__name__)


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
        on_delta=None,
    ):
        self.provider = provider
        self.strategy = strategy
        self.tools = tools or []
        self.memory = memory
        self.instructions = instructions
        self.config = config or RuntimeConfig()
        # on_delta(text, execution_id) — 주면 Provider가 스트리밍으로 호출한다.
        # 진입점은 여전히 run() 하나다(ADR-0006): 스트리밍은 부수 채널이지 두 번째 경로가 아니다.
        self.on_delta = on_delta
        self.runtime: Runtime | None = None  # 마지막 run의 Runtime

    async def _recall(self, task: str) -> str | None:
        """Memory → retrieve → Context 단방향 주입 (ADR-0002). 흐름의 유일한 진입점이다.

        기억은 사용자 지시 뒤에 붙어 system으로 들어가고, child도 instructions로 상속한다.
        """
        if self.memory is None:
            return self.instructions
        items = await self.memory.retrieve(task)
        # 조회어와 적중 수 — retrieve가 왜 빗나갔는지는 이 두 값 없이는 추측밖에 못 한다
        logger.debug('memory.retrieve query=%.60s hits=%d', task, len(items))
        if not items:
            return self.instructions
        recalled = '\n'.join(f'- {item.content}' for item in items)
        block = f'## What you remember from earlier runs\n{recalled}'
        return f'{self.instructions}\n\n{block}' if self.instructions else block

    async def run(self, task: str, context: Any = None, history: list | None = None) -> AgentResult:
        """유일한 진입점.

        - context: 거대 입력 — messages가 아니라 variables['context']로 들어간다.
        - history: 이전 턴들의 messages(멀티턴). 코어는 대화 이력을 소유하지 않는다 (ADR-0010) —
          앱이 자기 저장소에서 읽어 넘기고 `result.metadata['messages']`를 다시 저장한다.
          Memory와 혼동하지 말 것: history는 순서 있는 원문, Memory는 순서 없는 사실이다.
        """
        # 전략이 제안한 한도를 사용자가 명시하지 않은 자리에만 채운다 (ADR-0014).
        # root 전략에서 한 번만 — 한도는 run 전체가 공유하므로 child가 다시 올리지 않는다.
        config = resolve_limits(self.config, self.strategy.limits)
        runtime = self.runtime = Runtime(
            provider=self.provider, tools=self.tools, memory=self.memory, config=config,
            on_delta=self.on_delta,
        )
        runtime.default_strategy = self.strategy  # spawn 시 strategy 미지정이면 상속 (ADR-0006)
        node = runtime.execution.open(task)
        logger.info('run=%s exec=%s agent.started task=%.80s', runtime.run_id, node.id, task)
        ctx = Context(
            messages=[*(history or []), {'role': 'user', 'content': task}],
            instructions=await self._recall(task),
            variables={'context': context} if context is not None else {},
            metadata={'task': task, 'execution_id': node.id},
        )
        try:
            async with asyncio.timeout(config.timeout):  # None이면 무제한
                result = await runtime.run_strategy(self.strategy, ctx)
        except TimeoutError:
            result = AgentResult(
                status='budget_exceeded',
                result=ctx.last_assistant_text(),
                metadata={'reason': 'timeout', 'limit': config.timeout},
            )
        except asyncio.CancelledError:
            # 하드 취소(asyncio) — 프로그래밍 오류와 다른 사건이므로 tree에도 다르게 남긴다.
            # 부분 결과를 살리려면 이게 아니라 runtime.cancel()을 쓴다 (ADR-0011).
            runtime.execution.close(node.id, AgentResult(status='cancelled'))
            raise
        except BaseException:
            # root의 프로그래밍 오류는 숨기지 않는다 — tree에만 failed로 남기고 전파
            runtime.execution.close(node.id, AgentResult(status='failed'))
            raise
        # 다음 턴에 history로 그대로 되돌려 줄 transcript. Agent.run에만 붙인다 —
        # spawn_agent가 만드는 child의 AgentResult에는 실리지 않는다(재귀 context 폭발 방지).
        result.metadata['messages'] = ctx.messages
        # 코어가 남긴 기록(트리·로그)을 가리키는 이름. 앱은 자기 task_id 옆에 이걸 적어둔다.
        # 인자로 받지 않는다 — 외부 문자열에 유일성을 의존시키지 않는다 (ADR-0011).
        result.metadata['run_id'] = runtime.run_id
        # 사고 과정 — 호출 순서대로. messages와 같은 규칙이다: Agent.run에만 붙이고
        # child의 AgentResult에는 안 싣는다. 사고가 없으면(꺼짐/미지원) 키 자체가 없다 —
        # 빈 리스트를 넣으면 "껐다"와 "이 벤더는 안 준다"가 같아 보인다.
        if runtime.reasoning:
            result.metadata['reasoning'] = runtime.reasoning
        runtime.execution.close(node.id, result)
        logger.info(
            'run=%s exec=%s agent.finished status=%s tokens=%s',
            runtime.run_id, node.id, result.status, runtime.usage['total_tokens'],
        )
        return result
