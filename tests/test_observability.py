"""관찰 — 노드별 토큰과 로깅. 관찰이 실행에 영향을 주지 않아야 한다.

Event 시스템은 아직 만들지 않는다: 로그는 사람이 읽는 것이고, 프로그램이 소비할
구조화 스트림이 필요해지는 시점이 Phase 6이다.
"""
from __future__ import annotations

import asyncio
import logging

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import AgentResult
from strata import InMemory
from strata import MemoryItem
from strata import MemoryTool
from strata import ModelResponse
from strata import ReActStrategy
from strata import SpawnAgentTool
from strata import Strategy


def priced(text, tokens):
    return ModelResponse(text=text, usage={'total_tokens': tokens})


# --- 노드별 usage ---------------------------------------------------------------

class SpawnTwice(Strategy):
    """root가 child 둘을 띄운다 — 어느 가지가 비쌌는지 보기 위해."""

    async def execute(self, context, runtime):
        if context.metadata.get('execution_id') != 'exec_0':
            await runtime.generate(context)
            return AgentResult(result='child')
        await runtime.generate(context)
        await runtime.spawn_agent('싼 조각', context)
        await runtime.spawn_agent('비싼 조각', context)
        return AgentResult(result='root')


def test_node_usage_and_subtree_rollup():
    provider = ScriptedProvider([priced('root', 10), priced('cheap', 5), priced('expensive', 100)])
    agent = Agent(provider=provider, strategy=SpawnTwice())
    asyncio.run(agent.run('루트'))

    root = agent.runtime.execution.root
    cheap, expensive = root.children

    assert root.usage['total_tokens'] == 10, '노드가 직접 쓴 것만 센다'
    assert cheap.usage['total_tokens'] == 5
    assert expensive.usage['total_tokens'] == 100
    assert root.subtree_usage()['total_tokens'] == 115, '자손 포함 합계'
    assert agent.runtime.usage['total_tokens'] == 115, 'run 총합과 일치해야 한다'


# --- 로깅 -----------------------------------------------------------------------

def test_logs_carry_run_id_and_execution_id(caplog):
    """워커가 여럿이면 id 없이는 줄을 실행 단위로 묶을 수 없다 (ADR-0011)."""
    provider = ScriptedProvider([call('remember', content='사실'), final('했습니다')])
    with caplog.at_level(logging.DEBUG, logger='strata'):
        result = asyncio.run(
            Agent(
                provider=provider, strategy=ReActStrategy(), tools=[MemoryTool()], memory=InMemory(),
            ).run('기억해'),
        )

    run_id = result.metadata['run_id']
    text = caplog.text
    for event in (
        'agent.started', 'provider.request', 'provider.response', 'tool.started',
        'tool.finished', 'memory.store', 'agent.finished',
    ):
        assert event in text, f'{event} 로그가 없다'
    assert text.count(f'run={run_id}') >= 5, '모든 줄이 같은 run으로 묶여야 한다'
    assert 'exec=exec_0' in text


def test_memory_retrieve_logs_query_and_hit_count(caplog):
    """retrieve가 왜 빗나갔는지는 이 두 값 없이는 추측밖에 못 한다."""
    memory = InMemory()
    asyncio.run(memory.store(MemoryItem(content='사용자는 uv를 쓴다')))
    provider = ScriptedProvider([final('ok'), final('ok')])

    with caplog.at_level(logging.DEBUG, logger='strata'):
        asyncio.run(Agent(provider=provider, strategy=ReActStrategy(), memory=memory).run('uv 얘기'))
        asyncio.run(Agent(provider=provider, strategy=ReActStrategy(), memory=memory).run('전혀 무관'))

    assert 'memory.retrieve query=uv 얘기 hits=1' in caplog.text
    assert 'memory.retrieve query=전혀 무관 hits=0' in caplog.text


def test_library_is_silent_without_a_handler(caplog):
    """관찰이 실행에 영향을 주지 않는다 — 핸들러가 없으면 아무것도 나가지 않는다."""
    with caplog.at_level(logging.WARNING, logger='strata'):
        asyncio.run(Agent(provider=ScriptedProvider([final('ok')]), strategy=ReActStrategy()).run('조용히'))
    assert caplog.text == '', f'기본 상태에서 시끄럽다: {caplog.text}'


# --- 회귀: 취소가 Tool 안에서 삼켜지면 안 된다 --------------------------------------

def test_cancel_is_not_swallowed_by_spawn_agent_tool():
    """SpawnAgentTool은 Tool이지만 안에서 spawn을 부른다 — execute_tool이 삼키면 취소가 먹지 않는다."""
    class CancelThenSpawn(Strategy):
        def tools(self, runtime):
            return [SpawnAgentTool()]

        async def execute(self, context, runtime):
            if context.metadata.get('execution_id') != 'exec_0':
                return AgentResult(result='child')
            runtime.cancel('stop')
            observation = await runtime.execute_tool(
                'spawn_agent', {'task': '새 child'}, context,
                tools={t.name: t for t in self.tools(runtime)},
            )
            raise AssertionError(f'취소가 관찰로 삼켜졌다: {observation!r}')

    result = asyncio.run(Agent(provider=ScriptedProvider([]), strategy=CancelThenSpawn()).run('루트'))
    assert result.status == 'cancelled'


if __name__ == '__main__':
    print('pytest로 실행하세요 (caplog fixture 사용): uv run pytest tests/test_observability.py')
