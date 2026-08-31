"""취소 — 하드(asyncio)와 협조적(runtime.cancel) 두 종류 (ADR-0011).

핵심 차이: 하드는 지금까지 쓴 토큰을 버리고, 협조적은 살린다.
"""
from __future__ import annotations

import asyncio
import uuid

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata.agent import Agent
from strata.strategies import AgentResult
from strata.strategies import ReActStrategy
from strata.strategies import Strategy
from strata.tools import Tool


class SlowTool(Tool):
    name = 'slow'
    description = 'takes a while'
    input_schema = {'type': 'object', 'properties': {}}

    async def execute(self, env, **kwargs):
        await asyncio.sleep(10)
        return 'done'


class CancelAfterFirstAnswer(Strategy):
    """첫 응답을 받은 뒤 스스로 취소를 요청한다 — 외부 취소 채널의 대역."""

    async def execute(self, context, runtime):
        response = await runtime.generate(context)
        context.messages.append({'role': 'assistant', 'content': response.text})
        runtime.cancel('user requested')
        await runtime.generate(context)  # 여기서 Cancelled — run_strategy가 계약으로 변환
        raise AssertionError('취소 신호가 올라오지 않았다')


def test_cooperative_cancel_keeps_the_partial_answer():
    """협조적 취소의 존재 이유 — 이미 쓴 토큰을 살린다."""
    provider = ScriptedProvider([final('절반쯤 했습니다'), final('여기까지는 안 온다')])
    result = asyncio.run(Agent(provider=provider, strategy=CancelAfterFirstAnswer()).run('긴 작업'))

    assert result.status == 'cancelled'
    assert result.result == '절반쯤 했습니다', '지금까지의 답이 버려지면 안 된다'
    assert result.metadata['reason'] == 'user requested'
    # 취소 검사가 Provider 호출 **앞**에 있다 — 취소 후 LLM 비용이 0이라는 뜻이다
    assert len(provider.seen) == 1, '취소 후 provider를 다시 부르면 안 된다'


def test_cooperative_cancel_blocks_new_children():
    """취소 후에는 새 child를 띄우지 않는다 — 비싼 재귀가 계속 퍼지면 안 된다."""
    class SpawnAfterCancel(Strategy):
        async def execute(self, context, runtime):
            if context.metadata.get('execution_id') != 'exec_0':
                return AgentResult(result='child')
            runtime.cancel()
            await runtime.spawn_agent('새 child', context)
            raise AssertionError('spawn이 취소를 무시했다')

    result = asyncio.run(Agent(provider=ScriptedProvider([]), strategy=SpawnAfterCancel()).run('루트'))
    assert result.status == 'cancelled'
    assert result.metadata['run_id'], '취소돼도 run_id는 돌아온다'


def test_hard_cancel_propagates_and_is_recorded_as_cancelled():
    """asyncio 취소는 즉시 끊는다 — 부분 결과는 없고, tree에는 failed가 아닌 cancelled로 남는다."""
    async def scenario():
        agent = Agent(
            provider=ScriptedProvider([call('slow'), final('안 온다')]),
            strategy=ReActStrategy(), tools=[SlowTool()],
        )
        task = asyncio.create_task(agent.run('오래 걸리는 일'))
        await asyncio.sleep(0.05)  # tool 안으로 들어갈 시간
        task.cancel()
        try:
            await task
            raise AssertionError('취소가 삼켜졌다')
        except asyncio.CancelledError:
            pass
        return agent.runtime.execution.root

    node = asyncio.run(scenario())
    assert node.status == 'cancelled', f'failed가 아니라 cancelled여야 한다: {node.status}'


def test_run_id_is_returned_and_shared_by_children():
    """run_id는 코어가 발급한다. 재귀 전체가 하나의 run이므로 child도 같은 값을 쓴다."""
    seen = {}

    class Spawner(Strategy):
        async def execute(self, context, runtime):
            if context.metadata.get('execution_id') != 'exec_0':
                seen['child'] = runtime.run_id
                return AgentResult(result='child')
            seen['root'] = runtime.run_id
            await runtime.spawn_agent('조각', context)
            return AgentResult(result='root')

    result = asyncio.run(Agent(provider=ScriptedProvider([]), strategy=Spawner()).run('루트'))

    assert uuid.UUID(result.metadata['run_id']).version == 7
    assert seen['root'] == seen['child'] == result.metadata['run_id']


def test_run_id_differs_between_runs():
    """exec_0은 run마다 재사용된다 — run_id가 그걸 구분하는 층이다."""
    agent = Agent(provider=ScriptedProvider([final('a'), final('b')]), strategy=ReActStrategy())
    first = asyncio.run(agent.run('첫 번째'))
    second = asyncio.run(agent.run('두 번째'))

    assert first.metadata['run_id'] != second.metadata['run_id']
    assert agent.runtime.execution.root.id == 'exec_0', 'exec_id는 run마다 재사용된다 — 그래서 run_id가 필요하다'
    # 시간순 정렬은 test_ids.py가 검증한다 — 같은 밀리초 안에서는 순서가 무작위이기 때문(문서화된 한계)


def test_agent_run_does_not_accept_an_external_id():
    """ADR-0011 — 외부 id를 받지 않는다. 받으면 기록의 유일성이 앱 손에 넘어간다."""
    import inspect
    assert 'run_id' not in inspect.signature(Agent.run).parameters


if __name__ == '__main__':
    test_cooperative_cancel_keeps_the_partial_answer()
    test_cooperative_cancel_blocks_new_children()
    test_hard_cancel_propagates_and_is_recorded_as_cancelled()
    test_run_id_is_returned_and_shared_by_children()
    test_run_id_differs_between_runs()
    test_agent_run_does_not_accept_an_external_id()
    print('cancellation ok')
