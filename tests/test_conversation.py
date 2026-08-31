"""멀티턴 — 대화 이력은 코어가 아니라 앱이 소유한다 (ADR-0010).

Context(한 run) ≠ Conversation(run 사이) ≠ Memory(영속되는 사실) 셋을 가르는 테스트다.
history는 순서 있는 원문, Memory는 순서 없는 사실 — 서로를 대신하지 못한다.
"""
from __future__ import annotations

import asyncio
import json

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata.agent import Agent
from strata.memory import InMemory
from strata.memory import MemoryItem
from strata.runtime import RuntimeConfig
from strata.strategies import AgentResult
from strata.strategies import ReActStrategy
from strata.strategies import Strategy
from strata.tools import MemoryTool


def turns(provider, index=-1):
    """해당 호출에서 모델이 받은 대화만 — system(Strategy prompt + Memory)은 걷어낸다."""
    return [(m['role'], m['content']) for m in provider.seen[index] if m['role'] != 'system']


def make_agent(provider, **kwargs):
    return Agent(provider=provider, strategy=ReActStrategy(), **kwargs)


def test_second_turn_sees_the_first_turn():
    provider = ScriptedProvider([final('서울입니다'), final('맑습니다')])

    turn1 = asyncio.run(make_agent(provider).run('수도가 어디야?'))
    turn2 = asyncio.run(make_agent(provider).run('거기 날씨는?', history=turn1.metadata['messages']))

    assert turns(provider, 1) == [
        ('user', '수도가 어디야?'),
        ('assistant', '서울입니다'),
        ('user', '거기 날씨는?'),
    ], '이전 턴이 순서대로 앞에 붙어야 한다'
    assert turn2.result == '맑습니다'


def test_transcript_round_trips_across_many_turns():
    """앱이 저장소에 넣었다 뺐다 하는 패턴 — metadata['messages']를 그대로 다시 넘긴다."""
    provider = ScriptedProvider([final('1'), final('2'), final('3')])
    stored: list = []  # 앱의 DB 자리

    for task in ('첫째', '둘째', '셋째'):
        result = asyncio.run(make_agent(provider).run(task, history=stored))
        stored = result.metadata['messages']

    assert [m['content'] for m in stored] == ['첫째', '1', '둘째', '2', '셋째', '3']
    assert len(turns(provider)) == 5, '마지막 호출은 이전 4개 + 이번 user'


def test_history_is_optional_and_defaults_to_a_fresh_conversation():
    provider = ScriptedProvider([final('ok'), final('ok')])
    asyncio.run(make_agent(provider).run('첫 질문'))
    asyncio.run(make_agent(provider).run('무관한 질문'))
    assert [c for _, c in turns(provider, 1)] == ['무관한 질문'], 'history 없이는 매번 새 대화다'


def test_tool_turns_survive_into_the_next_turn():
    """ReAct의 tool 왕복도 transcript에 남아야 다음 턴이 맥락을 잃지 않는다."""
    provider = ScriptedProvider([call('remember', content='사실'), final('저장했습니다'), final('네')])

    turn1 = asyncio.run(
        Agent(
            provider=provider, strategy=ReActStrategy(), tools=[MemoryTool()], memory=InMemory(),
        ).run('기억해'),
    )
    roles = [m['role'] for m in turn1.metadata['messages']]
    assert 'tool' in roles, f'tool 관찰이 사라졌다: {roles}'

    asyncio.run(make_agent(provider).run('고마워', history=turn1.metadata['messages']))
    assert [r for r, _ in turns(provider)][:len(roles)] == roles


def test_transcript_is_pure_json():
    """ADR-0010의 전제 — 앱은 transcript를 DB/Redis에 저장한다. 직렬화가 안 되면 계약이 무의미하다.

    tool_calls에 ToolCall 객체가 담기면 여기서 TypeError로 잡힌다(실제로 그랬다).
    """
    provider = ScriptedProvider([call('remember', content='사실'), final('저장했습니다'), final('네')])
    turn1 = asyncio.run(
        Agent(
            provider=provider, strategy=ReActStrategy(), tools=[MemoryTool()], memory=InMemory(),
        ).run('기억해'),
    )

    raw = json.dumps(turn1.metadata['messages'])  # 앱의 저장소로 나가는 지점
    restored = json.loads(raw)                    # 다음 턴에 돌아오는 지점
    assert restored == turn1.metadata['messages']

    # 직렬화를 왕복한 history로도 대화가 이어져야 한다 — Provider가 dict를 읽어야 한다는 뜻이다
    result = asyncio.run(make_agent(provider).run('고마워', history=restored))
    assert result.status == 'completed'
    assert any(m.get('tool_calls') for m in restored), 'tool_calls가 실제로 들어있는 케이스여야 의미가 있다'


class SpawningStrategy(Strategy):
    """child 하나를 띄우고 그 결과를 들고 있는다 — 계약에 뭐가 실리는지 보기 위해."""

    def __init__(self):
        self.child_result: AgentResult | None = None

    async def execute(self, context, runtime):
        if context.metadata.get('execution_id') != 'exec_0':  # child 자신
            return AgentResult(result='child done')
        self.child_result = await runtime.spawn_agent('조각 작업', context)
        return AgentResult(result='root done')


def test_child_results_do_not_carry_a_transcript():
    """불변식 4 회귀 방지 — transcript는 Agent.run에만 붙는다. child가 들고 오면 재귀에서 폭발한다."""
    strategy = SpawningStrategy()
    root = asyncio.run(Agent(provider=ScriptedProvider([]), strategy=strategy).run('루트 작업'))

    assert 'messages' in root.metadata, 'root는 다음 턴을 위해 transcript를 돌려준다'
    assert 'messages' not in strategy.child_result.metadata, 'child → parent 계약에는 실리지 않는다'


def test_truncated_run_still_returns_what_it_had():
    """한도 초과로 잘려도 transcript는 돌아온다 — 대화를 이어갈 수 있어야 한다."""
    provider = ScriptedProvider([call('remember', content='x'), call('remember', content='y')])
    agent = Agent(
        provider=provider, strategy=ReActStrategy(), tools=[MemoryTool()],
        memory=InMemory(), config=RuntimeConfig(max_iterations=2),
    )
    result = asyncio.run(agent.run('계속 해봐'))

    assert result.status == 'budget_exceeded'
    assert result.metadata['messages'][0]['content'] == '계속 해봐'


def test_history_and_memory_are_different_things():
    """history는 순서 있는 원문, Memory는 순서 없는 사실 — 같은 run에 둘 다 들어간다."""
    memory = InMemory()
    asyncio.run(memory.store(MemoryItem(content='사용자는 uv를 쓴다')))
    provider = ScriptedProvider([final('네')])

    asyncio.run(
        Agent(provider=provider, strategy=ReActStrategy(), memory=memory).run(
            'uv 얘기', history=[{'role': 'user', 'content': '이전 턴'}],
        ),
    )
    system = provider.seen[0][0]
    assert system['role'] == 'system' and '사용자는 uv를 쓴다' in system['content'], 'Memory는 system 지시로'
    assert [c for _, c in turns(provider, 0)] == ['이전 턴', 'uv 얘기'], 'history는 messages로'


if __name__ == '__main__':
    test_second_turn_sees_the_first_turn()
    test_transcript_round_trips_across_many_turns()
    test_history_is_optional_and_defaults_to_a_fresh_conversation()
    test_tool_turns_survive_into_the_next_turn()
    test_transcript_is_pure_json()
    test_child_results_do_not_carry_a_transcript()
    test_truncated_run_still_returns_what_it_had()
    test_history_and_memory_are_different_things()
    print('conversation ok')
