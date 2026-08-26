"""Provider 넷 — Claude / Gemini / OpenRouter / vLLM, 그리고 스트리밍.

실행(키가 있는 것만 실제로 호출한다):
    export ANTHROPIC_API_KEY=sk-ant-...      # 또는 OPENAI_API_KEY / OPENROUTER_API_KEY / GEMINI_API_KEY
    uv run python examples/providers.py

**검증 상태**: 실제 API로 확인된 건 OpenAI 경로뿐이다. Claude·Gemini·OpenRouter·vLLM은
코드와 단위 테스트만 있고 호출해본 적이 없다 — 이 파일을 키와 함께 돌리는 것이 그 검증이다.
특히 usage가 0으로 새지 않는지 보라(OpenAI 호환 계층이 stream_options를 안 받으면 샌다).

핵심: **넷 중 셋은 같은 코드다.** OpenAI-compatible 엔드포인트라 base_url만 다르다.
별도 구현이 필요한 건 Anthropic 하나뿐이다 — 메시지 형식이 근본적으로 다르기 때문이다
(system이 최상위 파라미터, tool 호출/결과가 content block).
"""
from __future__ import annotations

import asyncio
import os

from strata import Agent
from strata import AnthropicProvider
from strata import OpenAIProvider
from strata import ReActStrategy
from strata import Tool

try:
    from dotenv import load_dotenv
    load_dotenv()  # .env 로딩은 프레임워크가 아닌 앱(이 예제)의 몫
except ImportError:
    pass


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers and return their sum'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
        'required': ['a', 'b'],
    }

    async def execute(self, env, **kwargs):
        return kwargs['a'] + kwargs['b']


def available():
    """키가 있는 Provider만. max_retries는 SDK가 지수 백오프로 처리한다 (ADR-0012)."""
    providers = []
    if os.environ.get('ANTHROPIC_API_KEY'):
        providers.append((
            'Claude', AnthropicProvider(
                model=os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5'), max_retries=3,
            ),
        ))
    if os.environ.get('OPENAI_API_KEY'):
        providers.append(('OpenAI', OpenAIProvider(model='gpt-4o-mini', max_retries=3)))
    if os.environ.get('OPENROUTER_API_KEY'):
        providers.append((
            'OpenRouter', OpenAIProvider(
                model=os.environ.get('OPENROUTER_MODEL', 'anthropic/claude-sonnet-4'),
                api_key=os.environ['OPENROUTER_API_KEY'],
                base_url='https://openrouter.ai/api/v1', max_retries=3,
            ),
        ))
    if os.environ.get('GEMINI_API_KEY'):
        providers.append((
            'Gemini', OpenAIProvider(
                model=os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash'),
                api_key=os.environ['GEMINI_API_KEY'],
                base_url='https://generativelanguage.googleapis.com/v1beta/openai/', max_retries=3,
            ),
        ))
    if os.environ.get('VLLM_BASE_URL'):
        providers.append((
            'vLLM', OpenAIProvider(
                model=os.environ.get('VLLM_MODEL', 'local'),
                api_key='not-needed', base_url=os.environ['VLLM_BASE_URL'],
            ),
        ))
    return providers


async def main():
    providers = available()
    if not providers:
        raise SystemExit(
            '키가 하나도 없습니다. 아래 중 하나를 설정하세요:\n'
            '  ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY / GEMINI_API_KEY / VLLM_BASE_URL',
        )

    for name, provider in providers:
        print(f'\n=== {name} ({type(provider).__name__}) ===')

        # on_delta를 주면 스트리밍. 안 주면 한 번에 — Strategy 코드는 양쪽 다 동일하다 (ADR-0012).
        def show(text, execution_id):
            print(text, end='', flush=True)

        agent = Agent(
            provider=provider, strategy=ReActStrategy(), tools=[AddTool()], on_delta=show,
        )
        result = await agent.run('add tool로 123456 + 654321을 계산하고 한 문장으로 답해줘.')
        print(f"\n  → status={result.status} tokens={agent.runtime.usage['total_tokens']}")
        print(f"  → run_id={result.metadata['run_id']}")


if __name__ == '__main__':
    asyncio.run(main())
