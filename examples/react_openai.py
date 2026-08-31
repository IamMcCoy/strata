"""ReAct + 실제 OpenAI Provider 예제.

실행:
    export OPENAI_API_KEY=sk-...
    uv run python examples/react_openai.py

모델 변경(기본 gpt-4o-mini): OPENAI_MODEL=<model>
vLLM/Ollama 등 OpenAI-compatible 서버: OpenAIProvider(base_url=...) 지정.
"""
from __future__ import annotations

import asyncio
import os

from strata.agent import Agent
from strata.providers import OpenAIProvider
from strata.strategies import ReActStrategy
from strata.tools import Tool


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers and return their sum'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
        'required': ['a', 'b'],
    }

    async def execute(self, env, **kwargs):
        print(f"  [tool] add({kwargs['a']}, {kwargs['b']})")
        return kwargs['a'] + kwargs['b']


try:
    from dotenv import load_dotenv
    load_dotenv()  # .env 로딩은 프레임워크가 아닌 앱(이 예제)의 몫
except ImportError:
    pass


async def main():
    if not os.environ.get('OPENAI_API_KEY'):
        raise SystemExit('OPENAI_API_KEY를 설정하세요: export OPENAI_API_KEY=sk-...')

    agent = Agent(
        provider=OpenAIProvider(
            model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
            model_params={'temperature': 0},   # 이 Provider의 모든 호출에 적용되는 배포 기본값
        ),
        strategy=ReActStrategy(),   # fake provider 예제(react.py)와 완전히 동일한 Strategy
        tools=[AddTool()],
    )
    result = await agent.run('add tool로 123456 + 654321을 계산하고 숫자만 답해줘.')
    print(f'status: {result.status}')
    print(f'result: {result.result}')


if __name__ == '__main__':
    asyncio.run(main())
