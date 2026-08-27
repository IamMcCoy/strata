"""RLM + 실제 OpenAI Provider 예제 — 거대 입력을 변수로 두고 모델이 코드로 분할 정복한다.

실행:
    export OPENAI_API_KEY=sk-...
    uv run python examples/rlm_openai.py

모델 변경(기본 gpt-4o-mini): OPENAI_MODEL=<model>
주의: PythonTool은 샌드박스 없이 이 프로세스에서 모델 코드를 exec한다 — 신뢰된 환경에서만.
"""
from __future__ import annotations

import asyncio
import os
import random

from strata import Agent
from strata import OpenAIProvider
from strata import RLMStrategy
from strata import RuntimeConfig

try:
    from dotenv import load_dotenv
    load_dotenv()  # .env 로딩은 프레임워크가 아닌 앱(이 예제)의 몫
except ImportError:
    pass


def make_document(chapters: int = 6, filler: int = 300) -> tuple[str, int]:
    """각 장에 '비밀 코드'가 하나씩 숨은 긴 문서. 정답(합)을 함께 돌려준다."""
    rng = random.Random(42)
    parts, total = [], 0
    for i in range(1, chapters + 1):
        code = rng.randint(100, 999)
        total += code
        noise = ' '.join(f'문장{j}은 중요하지 않은 내용이다.' for j in range(filler))
        parts.append(f'## 제{i}장\n{noise}\n이 장의 비밀 코드는 {code}이다.\n{noise}')
    return '\n\n'.join(parts), total


def render(node, indent=0):
    result = (node.result.result or '')[:60] if node.result else ''
    head = f"{'  ' * indent}- [{node.status}] depth={node.depth} iters={node.iterations}"
    print(f'{head} {node.task[:30]!r} → {result!r}')
    for child in node.children:
        render(child, indent + 1)


async def main():
    if not os.environ.get('OPENAI_API_KEY'):
        raise SystemExit('OPENAI_API_KEY를 설정하세요: export OPENAI_API_KEY=sk-...')

    document, answer = make_document()
    agent = Agent(
        provider=OpenAIProvider(model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')),
        strategy=RLMStrategy(model_params={'temperature': 0}),   # 패턴별 파라미터 — Provider 기본값보다 우선
        instructions='한국어로 답하라. 최종 답에는 합계 숫자를 반드시 포함하라.',
        config=RuntimeConfig(max_depth=2, max_iterations=15, token_budget=300_000),
    )
    result = await agent.run(
        '문서의 각 장에 숨은 "비밀 코드"를 모두 찾아 합계를 구하라. '
        '문서는 매우 기니 python tool로 장 단위로 나누고 llm_query로 각 장을 처리하라.',
        context=document,
    )
    print(f'status: {result.status}')
    print(f'result: {result.result}')
    print(f'expected sum: {answer}')
    print(f'usage: {agent.runtime.usage}')
    print('\nExecution Tree:')
    render(agent.runtime.execution.root)


if __name__ == '__main__':
    asyncio.run(main())
