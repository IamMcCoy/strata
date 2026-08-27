"""trim_history — 턴 경계에서만 자른다. tool 왕복 쌍이 깨지면 프로바이더가 400을 낸다."""
from __future__ import annotations

import asyncio

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import ReActStrategy
from strata import Tool
from strata import trim_history


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers'
    input_schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}}}

    async def execute(self, env, **kwargs):
        return kwargs['a'] + kwargs['b']


def pairs_are_intact(messages):
    """tool 결과는 반드시 그 id를 호출한 assistant 뒤에 와야 한다 — 프로바이더의 요구사항."""
    announced = set()
    for message in messages:
        for tool_call in message.get('tool_calls') or []:
            announced.add(tool_call['id'])
        if message.get('role') == 'tool' and message['tool_call_id'] not in announced:
            return False
    return True


def conversation(turns):
    """turns개의 턴. 각 턴은 user → assistant(tool_call) → tool → assistant."""
    messages = []
    for index in range(turns):
        messages += [
            {'role': 'user', 'content': f'질문 {index}'},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call_{index}', 'name': 'add'}]},
            {'role': 'tool', 'tool_call_id': f'call_{index}', 'name': 'add', 'content': str(index)},
            {'role': 'assistant', 'content': f'답 {index}', 'tool_calls': []},
        ]
    return messages


def test_keeps_the_last_n_turns_whole():
    trimmed = trim_history(conversation(5), keep_turns=2)
    assert [m['content'] for m in trimmed if m['role'] == 'user'] == ['질문 3', '질문 4']
    assert len(trimmed) == 8  # 턴당 4개 메시지가 통째로


def test_never_splits_a_tool_call_pair():
    """핵심: 순진한 슬라이스는 쌍을 깨서 조용히 400을 만든다."""
    full = conversation(5)
    assert not pairs_are_intact(full[-6:])          # messages[-6:] 은 실제로 깨진다
    for keep in range(1, 6):
        assert pairs_are_intact(trim_history(full, keep)), keep


def test_result_always_starts_a_turn():
    """잘린 결과의 첫 메시지는 언제나 user — 그래야 앞이 잘린 흔적이 남지 않는다."""
    for keep in range(1, 6):
        trimmed = trim_history(conversation(5), keep_turns=keep)
        assert trimmed[0]['role'] == 'user'


def test_shorter_history_is_returned_whole():
    full = conversation(2)
    assert trim_history(full, keep_turns=10) == full


def test_zero_or_negative_keeps_nothing():
    assert trim_history(conversation(3), keep_turns=0) == []
    assert trim_history(conversation(3), keep_turns=-1) == []


def test_does_not_mutate_the_input():
    full = conversation(3)
    before = len(full)
    trim_history(full, keep_turns=1)
    assert len(full) == before


def test_empty_history_is_fine():
    assert trim_history([], keep_turns=3) == []


def test_round_trip_through_agent_run():
    """실제 사용 모양 — 앱이 저장한 transcript를 잘라서 다음 턴에 넣는다 (ADR-0010)."""
    provider = ScriptedProvider([call('add', a=1, b=2), final('3입니다'), final('아까 3이라고 했습니다')])
    agent = Agent(provider=provider, strategy=ReActStrategy(), tools=[AddTool()])

    first = asyncio.run(agent.run('1 더하기 2는?'))
    stored = first.metadata['messages']

    second = asyncio.run(agent.run('방금 뭐라고 했지?', history=trim_history(stored, keep_turns=5)))
    assert second.status == 'completed'
    # 턴 1의 tool 왕복이 통째로 실려 갔고 쌍이 살아 있다
    sent = provider.seen[-1]  # ScriptedProvider.seen = 호출별 메시지 스냅샷
    assert pairs_are_intact(sent)
    assert any(m.get('role') == 'tool' for m in sent)
