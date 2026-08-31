"""Router 최소 예제 — 과제에 맞는 전략을 고르고, 고른 전략이 끝까지 푼다.

실행: uv run python examples/router.py

라우터는 문제를 "푸는" 패턴이 아니라 "배분하는" 패턴이다. 고른 전략을 **같은 Context에서**
그대로 실행하므로 대화 이력과 변수가 살아있다 — child로 띄우면 멀티턴이 깨진다.

거대 입력이 오면 모델에게 묻지도 않는다: `variables['context']`가 있다는 건
"한 윈도우에 안 들어간다"는 사실이지 판단이 아니다.
"""
from __future__ import annotations

import asyncio

from strata.agent import Agent
from strata.providers import ModelResponse
from strata.providers import Provider
from strata.providers import ToolCall
from strata.strategies import AgentResult
from strata.strategies import RouterStrategy
from strata.strategies import Strategy


class Announce(Strategy):
    """실제 전략 대신 자기 이름만 답한다 — 무엇이 골라졌는지 보이게."""

    def __init__(self, name, description):
        super().__init__()
        self.name = name
        self.description = description

    async def execute(self, context, runtime):
        return AgentResult(result=f'[{self.name}] 이 전략이 과제를 처리했습니다')


class ScriptedProvider(Provider):
    """LLM 흉내: 과제 문장을 보고 route tool을 호출한다."""

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')
        pick = 'reflection' if '문단' in task else 'recursive' if '조사' in task else 'react'
        return ModelResponse(tool_calls=[ToolCall(name='route', arguments={'strategy': pick})])


def build():
    return Agent(
        provider=ScriptedProvider(),
        strategy=RouterStrategy(
            {
                'react': Announce('react', 'Solve it directly by calling tools in a loop.'),
                'recursive': Announce('recursive', 'Split into independent sub-problems.'),
                'reflection': Announce('reflection', 'Draft, critique, revise.'),
                'rlm': Announce('rlm', 'Input too large for one context window.'),
            },
            default='react',
        ),
    )


async def main():
    for task, context in [
        ('12 곱하기 34는?', None),
        ('회사 소개 문단을 써줘', None),
        ('에이전트 프레임워크 동향을 조사해줘', None),
        ('이 로그에서 오류를 찾아줘', 'ERROR ' * 5000),  # 거대 입력 → 묻지 않고 rlm
    ]:
        result = await build().run(task, context=context)
        asked = '규칙' if context is not None else '모델'
        print(f'{task[:28]:30} → route={result.metadata["route"]:10} ({asked}이 결정)')
        print(f'{"":30}   {result.result}')

    # 라우터는 계약을 그대로 올린다 — 고른 전략의 결과가 그대로 돌아온다
    result = await build().run('이 로그에서 오류를 찾아줘', context='x' * 100)
    assert result.metadata['route'] == 'rlm' and result.status == 'completed'


if __name__ == '__main__':
    asyncio.run(main())
