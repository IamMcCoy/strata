"""실제 OpenAI-compatible 엔드포인트 통합 테스트 — 키나 base_url이 있을 때만 실행된다.

OpenAI:
    export OPENAI_API_KEY=sk-...
    uv run pytest tests/test_openai_integration.py -q

vLLM·Ollama·OpenRouter 등 호환 엔드포인트 — base_url만 바꾼 같은 코드다:
    OPENAI_BASE_URL=http://192.168.1.70:32757/v1 OPENAI_MODEL=Gemma4-12B-it \
        uv run pytest tests/test_openai_integration.py -q

vLLM에서 tool 왕복을 보려면 서버가 `--enable-auto-tool-choice --tool-call-parser ...`로
떠 있어야 한다 — 없으면 tool을 넘기는 순간 400이다(코드가 아니라 서버 기동 옵션).
"""
from __future__ import annotations

import asyncio
import os

import pytest
from strata import Agent
from strata import OpenAIProvider
from strata import ReActStrategy
from strata import Tool

pytestmark = pytest.mark.skipif(
    not (os.environ.get('OPENAI_API_KEY') or os.environ.get('OPENAI_BASE_URL')),
    reason='OPENAI_API_KEY / OPENAI_BASE_URL 없음 — 통합 테스트 건너뜀',
)


def make_provider(**kwargs):
    """로컬 엔드포인트는 키를 요구하지 않으므로 자리표시자를 넣는다."""
    return OpenAIProvider(
        model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
        api_key=os.environ.get('OPENAI_API_KEY') or 'not-needed',
        base_url=os.environ.get('OPENAI_BASE_URL'),
        **kwargs,
    )


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers and return their sum'
    input_schema = {
        'type': 'object',
        'properties': {
            'a': {'type': 'integer'},
            'b': {'type': 'integer'},
        },
        'required': ['a', 'b'],
    }

    def __init__(self):
        self.calls = 0

    async def execute(self, env, **kwargs):
        self.calls += 1
        return kwargs['a'] + kwargs['b']


def test_react_loop_with_real_endpoint():
    """tool 왕복 — 모델이 암산으로 맞힌 것과 구분하려면 tool이 실제로 불렸는지를 봐야 한다."""
    tool = AddTool()
    agent = Agent(provider=make_provider(), strategy=ReActStrategy(), tools=[tool])

    result = asyncio.run(
        agent.run(
            'Use the add tool to compute 123456 + 654321. '
            'Then answer with just the number.',
        ),
    )

    assert result.status == 'completed'
    assert '777777' in (result.result or '')
    assert tool.calls >= 1, 'tool을 거치지 않고 답했다 — tool 왕복이 검증되지 않는다'


def test_streaming_reports_deltas_and_usage():
    """스트리밍에서 usage가 새지 않는지 — 호환 계층이 stream_options를 무시하면 0이 되고,
    그러면 token_budget이 조용히 무력화된다."""
    deltas: list[str] = []
    agent = Agent(
        provider=make_provider(),
        strategy=ReActStrategy(),
        on_delta=lambda text, execution_id: deltas.append(text),
    )

    result = asyncio.run(agent.run('Reply with exactly one short sentence.'))

    assert result.status == 'completed'
    assert deltas, 'on_delta가 한 번도 불리지 않았다 — 스트리밍 경로가 죽었다'
    assert agent.runtime.usage['total_tokens'] > 0
