"""스트리밍 — 부수 채널이지 계약이 아니다 (ADR-0012). 실제 API 호출 없음.

핵심 불변식: on_delta를 줘도 generate의 반환은 여전히 완결된 ModelResponse다.
그래서 Strategy는 스트리밍을 몰라도 되고, 한도·usage 집계가 한 경로로 유지된다.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from conftest import ScriptedProvider
from strata.agent import Agent
from strata.providers import ModelResponse
from strata.providers import Provider
from strata.providers.openai import _consume_stream
from strata.strategies import AgentResult
from strata.strategies import ReActStrategy
from strata.strategies import Strategy


def chunk(content=None, tool_call=None, usage=None):
    """OpenAI 스트리밍 청크 흉내. usage 청크는 choices가 비어 있다."""
    if usage is not None:
        return SimpleNamespace(
            choices=[], usage=SimpleNamespace(
                prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=usage[0] + usage[1],
            ),
        )
    delta = SimpleNamespace(content=content, tool_calls=[tool_call] if tool_call else None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def call_part(index, id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments))


async def as_stream(chunks):
    for c in chunks:
        yield c


def test_stream_accumulates_text_and_usage():
    seen: list[str] = []
    chunks = [chunk('안녕'), chunk('하세'), chunk('요'), chunk(usage=(10, 5))]
    response = asyncio.run(_consume_stream(as_stream(chunks), seen.append))

    assert seen == ['안녕', '하세', '요'], '도착하는 대로 흘러야 한다'
    assert response.text == '안녕하세요', '반환은 여전히 완결된 응답이다'
    assert response.usage['total_tokens'] == 15, 'usage가 새면 token_budget이 무의미해진다'


def test_stream_reassembles_split_tool_calls():
    """tool_calls는 조각으로 온다 — index별로 이어 붙이지 않으면 JSON이 깨진다."""
    chunks = [
        chunk(tool_call=call_part(0, id='call_x', name='add', arguments='{"a":')),
        chunk(tool_call=call_part(0, arguments=' 1, "b": 2}')),
        chunk(usage=(3, 4)),
    ]
    response = asyncio.run(_consume_stream(as_stream(chunks), None))

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == 'add'
    assert response.tool_calls[0].arguments == {'a': 1, 'b': 2}
    assert response.tool_calls[0].id == 'call_x'


class StreamingProvider(Provider):
    """on_delta를 받으면 조각으로 흘리고, 그래도 완결 응답을 반환한다."""

    async def generate(self, messages, tools=None, on_delta=None, **kwargs):
        text = '조각1 조각2'
        if on_delta is not None:
            for part in text.split():
                on_delta(part)
        return ModelResponse(text=text, usage={'total_tokens': 7})


def test_agent_streams_without_a_second_entry_point():
    """진입점은 run() 하나다 (ADR-0006) — 스트리밍이 두 번째 경로를 만들지 않는다."""
    seen = []
    agent = Agent(
        provider=StreamingProvider(), strategy=ReActStrategy(),
        on_delta=lambda text, execution_id: seen.append((text, execution_id)),
    )
    result = asyncio.run(agent.run('스트리밍'))

    assert [t for t, _ in seen] == ['조각1', '조각2']
    assert {e for _, e in seen} == {'exec_0'}, 'execution_id는 Runtime이 붙인다'
    assert result.result == '조각1 조각2', '완결 결과도 그대로 나온다'
    assert agent.runtime.usage['total_tokens'] == 7


def test_deltas_from_recursion_are_labelled_by_node():
    """재귀에서는 여러 child의 토큰이 섞인다 — execution_id가 없으면 누가 말하는지 모른다."""
    class Spawner(Strategy):
        async def execute(self, context, runtime):
            if context.metadata.get('execution_id') != 'exec_0':
                await runtime.generate(context)
                return AgentResult(result='child')
            await runtime.generate(context)
            await runtime.spawn_agent('조각', context)
            return AgentResult(result='root')

    seen = []
    agent = Agent(
        provider=StreamingProvider(), strategy=Spawner(),
        on_delta=lambda text, execution_id: seen.append(execution_id),
    )
    asyncio.run(agent.run('루트'))
    assert set(seen) == {'exec_0', 'exec_1'}, 'root와 child의 조각이 갈려야 한다'


def test_subscriber_exception_does_not_kill_the_run():
    """관찰이 실행에 영향을 주지 않는다 — 로깅과 같은 원칙."""
    def boom(text, execution_id):
        raise RuntimeError('구독자 폭발')

    result = asyncio.run(
        Agent(
            provider=StreamingProvider(), strategy=ReActStrategy(), on_delta=boom,
        ).run('스트리밍'),
    )
    assert result.status == 'completed'


def test_provider_is_not_asked_to_stream_when_nobody_listens():
    """on_delta가 없으면 아예 넘기지 않는다 — 스트리밍을 모르는 Provider도 그대로 동작한다."""
    provider = ScriptedProvider([ModelResponse(text='ok')])
    asyncio.run(Agent(provider=provider, strategy=ReActStrategy()).run('조용히'))
    assert provider.kwargs == [{}], f'on_delta가 새어 들어갔다: {provider.kwargs}'


if __name__ == '__main__':
    test_stream_accumulates_text_and_usage()
    test_stream_reassembles_split_tool_calls()
    test_agent_streams_without_a_second_entry_point()
    test_deltas_from_recursion_are_labelled_by_node()
    test_subscriber_exception_does_not_kill_the_run()
    test_provider_is_not_asked_to_stream_when_nobody_listens()
    print('streaming ok')
