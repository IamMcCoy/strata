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
from strata.agent import Agent
from strata.memory import InMemory
from strata.memory import MemoryItem
from strata.providers import ModelResponse
from strata.providers import ToolCall
from strata.strategies import AgentResult
from strata.strategies import ReActStrategy
from strata.strategies import Strategy
from strata.tools import MemoryTool
from strata.tools import SpawnAgentTool
from strata.tools import Tool


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


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers'
    input_schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}}}

    async def execute(self, env, **kwargs):
        return kwargs['a'] + kwargs['b']


def test_warns_when_a_tool_call_leaks_into_the_answer_text(caplog):
    """모델이 tool call 형식을 못 지키면 벤더 문법이 텍스트로 샌다.

    tool_calls가 비어 ReAct는 그것을 최종 답으로 보고 끝낸다 — 조용히 쓰레기가 정답이 된다.
    동작은 바꾸지 않고(오탐 가능) 경고만 남는지 확인한다. 실측: vLLM + Gemma4-12B.
    """
    leaked = '<|tool_call>call:add{"a": 1, "b": 2}'
    agent = Agent(provider=ScriptedProvider([final(leaked)]), strategy=ReActStrategy(), tools=[AddTool()])
    with caplog.at_level(logging.WARNING, logger='strata'):
        result = asyncio.run(agent.run('1 + 2'))

    assert result.status == 'completed' and result.result == leaked  # 동작은 그대로
    assert any('tool_call_may_have_leaked_as_text' in r.message for r in caplog.records)
    assert any("['add']" in str(r.args) for r in caplog.records)


def test_no_warning_when_the_answer_does_not_mention_a_tool(caplog):
    """평범한 최종 답에는 경고가 붙지 않는다 — 매 run마다 뜨면 아무도 안 읽는다."""
    agent = Agent(provider=ScriptedProvider([final('정답은 3입니다.')]), strategy=ReActStrategy(), tools=[AddTool()])
    with caplog.at_level(logging.WARNING, logger='strata'):
        asyncio.run(agent.run('1 + 2'))
    assert not [r for r in caplog.records if 'leaked' in r.message]


# --- 사고 과정(reasoning) --------------------------------------------------------

def test_reasoning_is_collected_per_call_and_returned_in_metadata():
    """사고는 generate 호출마다 따로 온다 — 합치면 어느 판단이 어느 턴 것인지 사라진다.

    답이 아니라 진단용이므로 result가 아니라 metadata로 나간다. messages와 같은 자리·같은 규칙.
    """
    agent = Agent(
        provider=ScriptedProvider([
            ModelResponse(tool_calls=[ToolCall(name='add', arguments={'a': 1, 'b': 2})], reasoning='더해야겠다'),
            ModelResponse(text='3', reasoning='3이 맞다'),
        ]),
        strategy=ReActStrategy(),
        tools=[AddTool()],
    )
    result = asyncio.run(agent.run('1 + 2'))

    assert result.result == '3', '사고가 답에 섞이면 안 된다'
    assert result.metadata['reasoning'] == ['더해야겠다', '3이 맞다']


def test_no_reasoning_key_when_thinking_is_off():
    """빈 리스트를 넣으면 '껐다'와 '이 벤더는 안 준다'가 같아 보인다 — 키 자체를 두지 않는다."""
    agent = Agent(provider=ScriptedProvider([final('3')]), strategy=ReActStrategy())
    result = asyncio.run(agent.run('1 + 2'))
    assert 'reasoning' not in result.metadata


def test_child_agent_reasoning_rolls_up_to_the_root_only():
    """Runtime은 run당 하나라 child의 사고도 root에 모인다 — child의 AgentResult에는 안 실린다.

    최상위 필드였다면 재귀 깊이마다 사고가 parent context로 올라간다(불변식 4).
    """
    captured: list = []

    class Parent(Strategy):
        async def execute(self, context, runtime):
            await runtime.generate(context)
            child = await runtime.spawn_agent('sub', context, strategy=Child())
            captured.append(child)
            return AgentResult(result='done')

    class Child(Strategy):
        async def execute(self, context, runtime):
            await runtime.generate(context)
            return AgentResult(result='child')

    provider = ScriptedProvider([
        ModelResponse(text='p', reasoning='부모의 사고'),
        ModelResponse(text='c', reasoning='자식의 사고'),
    ])
    result = asyncio.run(Agent(provider=provider, strategy=Parent()).run('t'))

    assert 'reasoning' not in captured[0].metadata, 'child 계약에 사고를 실으면 context가 폭발한다'
    assert result.metadata['reasoning'] == ['부모의 사고', '자식의 사고']
