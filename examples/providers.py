"""Provider 넷 — Claude / Gemini / OpenRouter / vLLM, 그리고 스트리밍.

실행(키가 있는 것만 실제로 호출한다):
    export ANTHROPIC_API_KEY=sk-ant-...      # 또는 OPENAI_API_KEY / OPENROUTER_API_KEY / GEMINI_API_KEY
    uv run python examples/providers.py

**검증 상태**: OpenAI·Gemini·vLLM은 스트리밍·tool 왕복·usage까지 실제 호출로 확인했다.
Claude·OpenRouter·Ollama는 미검증 — 이 파일을 키와 함께 돌리는 것이 그 검증이다. usage가 0으로 새지 않는지 보라(호환 계층이 stream_options를 안 받으면 샌다).

vLLM에서 tool을 쓰려면 서버가 `--enable-auto-tool-choice --tool-call-parser ...`로 떠 있어야
한다. 없으면 tool을 넘기는 순간 400이다 — 코드가 아니라 서버 기동 옵션이다.

vLLM/Ollama/OpenRouter는 OpenAI-compatible이라 `base_url`만 바꾼 **같은 코드**다.
별도 구현이 필요한 건 Claude와 Gemini — 둘 다 메시지 형식이 근본적으로 다르다:

  Claude  system이 최상위 파라미터, tool 호출/결과가 content block
  Gemini  system이 config, assistant가 role='model', tool 호출/결과가 part
"""
from __future__ import annotations

import asyncio
import os

from strata.agent import Agent
from strata.providers import AnthropicProvider
from strata.providers import GeminiProvider
from strata.providers import OpenAIProvider
from strata.strategies import ReActStrategy
from strata.tools import Tool

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
    if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
        # 네이티브 SDK. OpenAI 호환 엔드포인트도 여전히 되지만(base_url=...) 그쪽은 shim이라
        # stream_options 지원 등이 버전에 따라 갈린다.
        providers.append((
            'Gemini', GeminiProvider(
                model=os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash-lite'), max_retries=3,
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
        try:
            result = await agent.run('add tool로 123456 + 654321을 계산하고 한 문장으로 답해줘.')
        except Exception as exc:
            # 검증용 예제이므로 한 Provider가 죽어도 나머지를 계속 본다.
            # (코어는 이 예외를 삼키지 않는다 — root 예외는 앱이 봐야 한다, ADR-0012)
            print(f'\n  ✗ 실패: {type(exc).__name__}: {exc}')
            continue
        tokens = agent.runtime.usage['total_tokens']
        print(f'\n  → status={result.status} tokens={tokens}')
        print(f"  → run_id={result.metadata['run_id']}")
        if tokens == 0:
            print('  ⚠ usage가 0이다 — 이 경로는 token_budget이 무력화된다')


if __name__ == '__main__':
    asyncio.run(main())
