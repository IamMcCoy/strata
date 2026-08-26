"""인프라 오류와 프로그래밍 오류를 가른다 (ADR-0013).

재시도까지 소진된 429는 예산 소진과 같은 상황이다 — 더 못 가지만 지금까지의 답은 있다.
그래서 같은 결말을 준다. 반면 내 코드의 버그는 삼키지 않는다.
"""
from __future__ import annotations

import asyncio

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import AgentResult
from strata import ModelResponse
from strata import Provider
from strata import ProviderError
from strata import ReActStrategy
from strata import Strategy
from strata import Tool
from strata import ToolCall


class Echo(Tool):
    name = 'echo'
    description = 'echo'
    input_schema = {'type': 'object', 'properties': {}}

    async def execute(self, env, **kwargs):
        return 'ok'


def progressing():
    return ModelResponse(
        text='2장까지 분석했습니다',
        tool_calls=[ToolCall(name='echo', arguments={})],
        usage={'total_tokens': 400},
    )


class FailsOnThirdCall(Provider):
    """두 번 진행하고 세 번째에 인프라 오류 — SDK 재시도까지 소진된 상태."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, tools=None, on_delta=None, **kwargs):
        self.calls += 1
        if self.calls >= 3:
            raise ProviderError('RateLimitError: 429 Too Many Requests')
        return progressing()


def test_provider_error_keeps_the_partial_answer():
    """핵심 — 이미 지불한 토큰의 결과를 버리지 않는다."""
    agent = Agent(provider=FailsOnThirdCall(), strategy=ReActStrategy(), tools=[Echo()])
    result = asyncio.run(agent.run('문서 전체를 분석하라'))

    assert result.status == 'failed'
    assert result.metadata['reason'] == 'provider_error'
    assert '429' in result.metadata['detail'], '원인이 보여야 한다'
    assert result.result == '2장까지 분석했습니다', '지금까지의 답이 버려지면 안 된다'
    assert agent.runtime.usage['total_tokens'] == 800


def test_programming_errors_still_explode():
    """반대 방향 — 이걸 삼키면 사용자가 몇 시간을 디버깅한다."""
    class Buggy(Provider):
        async def generate(self, messages, tools=None, on_delta=None, **kwargs):
            return None.text  # type: ignore[attr-defined]

    try:
        asyncio.run(Agent(provider=Buggy(), strategy=ReActStrategy()).run('작업'))
    except AttributeError:
        return
    raise AssertionError('프로그래밍 오류가 삼켜졌다')


def test_transcript_survives_a_provider_error():
    """부분 결과를 살리는 이유의 절반 — 대화를 이어갈 수 있어야 한다 (ADR-0010)."""
    agent = Agent(provider=FailsOnThirdCall(), strategy=ReActStrategy(), tools=[Echo()])
    result = asyncio.run(agent.run('문서 전체를 분석하라'))

    assert result.metadata['messages'][0]['content'] == '문서 전체를 분석하라'
    assert result.metadata['run_id'], '실패해도 run_id는 돌아온다'


def test_child_provider_error_does_not_kill_the_parent():
    """child의 인프라 오류는 계약으로 변환돼 parent가 스스로 답한다."""
    class SpawnOnce(Strategy):
        def __init__(self):
            self.child: AgentResult | None = None

        async def execute(self, context, runtime):
            if context.metadata.get('execution_id') != 'exec_0':
                raise ProviderError('RateLimitError: child가 429를 맞았다')
            self.child = await runtime.spawn_agent('조각', context)
            return AgentResult(result='parent가 스스로 답함')

    strategy = SpawnOnce()
    result = asyncio.run(Agent(provider=ScriptedProvider([]), strategy=strategy).run('루트'))

    assert result.status == 'completed', 'child 실패가 parent를 죽이면 안 된다'
    assert strategy.child.status == 'failed'
    assert strategy.child.metadata['reason'] == 'provider_error'


def test_provider_error_is_not_swallowed_by_execute_tool():
    """Tool 안에서 올라온 인프라 오류가 관찰 문자열로 바뀌면 안 된다 (Cancelled와 같은 이유)."""
    class Exploding(Tool):
        name = 'boom'
        description = 'boom'
        input_schema = {'type': 'object', 'properties': {}}

        async def execute(self, env, **kwargs):
            raise ProviderError('APIConnectionError: 연결 끊김')

    agent = Agent(
        provider=ScriptedProvider([call('boom'), final('안 온다')]),
        strategy=ReActStrategy(), tools=[Exploding()],
    )
    result = asyncio.run(agent.run('작업'))
    assert result.status == 'failed'
    assert result.metadata['reason'] == 'provider_error'


# --- FallbackProvider --------------------------------------------------------

class AlwaysFails(Provider):
    async def generate(self, messages, tools=None, on_delta=None, **kwargs):
        raise ProviderError('RateLimitError: 429')


class StreamsThenFails(Provider):
    """조각을 흘린 뒤 실패한다 — 폴백하면 중복 출력되는 경우."""

    async def generate(self, messages, tools=None, on_delta=None, **kwargs):
        if on_delta is not None:
            on_delta('앞부분')
        raise ProviderError('APIConnectionError: 중간에 끊김')


class Works(Provider):
    async def generate(self, messages, tools=None, on_delta=None, **kwargs):
        if on_delta is not None:
            on_delta('대체 답')
        return ModelResponse(text='대체 답', usage={'total_tokens': 10})


def test_fallback_moves_to_the_next_provider():
    from strata import FallbackProvider
    agent = Agent(provider=FallbackProvider([AlwaysFails(), Works()]), strategy=ReActStrategy())
    result = asyncio.run(agent.run('작업'))
    assert result.status == 'completed' and result.result == '대체 답'


def test_fallback_reports_every_failure_when_all_fail():
    from strata import FallbackProvider
    agent = Agent(provider=FallbackProvider([AlwaysFails(), AlwaysFails()]), strategy=ReActStrategy())
    result = asyncio.run(agent.run('작업'))
    assert result.status == 'failed'
    assert result.metadata['detail'].count('AlwaysFails') == 2, '어떤 Provider들이 실패했는지 보여야 한다'


def test_fallback_does_not_duplicate_already_streamed_text():
    """이미 흘러간 조각이 있으면 폴백하지 않는다 — 사용자 화면에 텍스트가 두 번 나오면 안 된다."""
    from strata import FallbackProvider
    seen: list[str] = []
    agent = Agent(
        provider=FallbackProvider([StreamsThenFails(), Works()]),
        strategy=ReActStrategy(), on_delta=lambda text, execution_id: seen.append(text),
    )
    result = asyncio.run(agent.run('작업'))

    assert seen == ['앞부분'], f'대체 Provider의 텍스트가 덧붙으면 안 된다: {seen}'
    assert result.status == 'failed'


def test_fallback_does_not_retry_programming_errors():
    """버그에 폴백하면 같은 버그를 벤더 수만큼 반복 실행할 뿐이다."""
    from strata import FallbackProvider

    class Buggy(Provider):
        calls = 0

        async def generate(self, messages, tools=None, on_delta=None, **kwargs):
            type(self).calls += 1
            raise TypeError('내 코드 버그')

    try:
        asyncio.run(Agent(provider=FallbackProvider([Buggy(), Works()]), strategy=ReActStrategy()).run('작업'))
    except TypeError:
        assert Buggy.calls == 1, '버그에는 폴백하지 않는다'
        return
    raise AssertionError('프로그래밍 오류가 삼켜졌다')


if __name__ == '__main__':
    test_provider_error_keeps_the_partial_answer()
    test_programming_errors_still_explode()
    test_transcript_survives_a_provider_error()
    test_child_provider_error_does_not_kill_the_parent()
    test_provider_error_is_not_swallowed_by_execute_tool()
    test_fallback_moves_to_the_next_provider()
    test_fallback_reports_every_failure_when_all_fail()
    test_fallback_does_not_duplicate_already_streamed_text()
    test_fallback_does_not_retry_programming_errors()
    print('provider errors ok')
