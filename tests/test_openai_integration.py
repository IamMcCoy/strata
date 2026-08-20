"""실제 OpenAI API 통합 테스트 — OPENAI_API_KEY가 설정된 경우에만 실행된다.

실행:
    export OPENAI_API_KEY=sk-...
    uv run pytest tests/test_openai_integration.py -q

모델 변경(기본 gpt-4o-mini):
    OPENAI_MODEL=<model> uv run pytest tests/test_openai_integration.py -q
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
    not os.environ.get('OPENAI_API_KEY'),
    reason='OPENAI_API_KEY 없음 — 통합 테스트 건너뜀',
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

    async def execute(self, env, **kwargs):
        return kwargs['a'] + kwargs['b']


def test_react_loop_with_real_openai():
    provider = OpenAIProvider(model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'))
    agent = Agent(provider=provider, strategy=ReActStrategy(), tools=[AddTool()])

    result = asyncio.run(
        agent.run(
            'Use the add tool to compute 123456 + 654321. '
            'Then answer with just the number.',
        ),
    )

    assert result.status == 'completed'
    assert '777777' in (result.result or '')
