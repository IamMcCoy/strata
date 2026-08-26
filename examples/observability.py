"""로그와 노드별 토큰 — 재귀 실행 안에서 무슨 일이 일어났는지 본다.

실행: uv run python examples/observability.py

strata는 핸들러를 달지 않는다(NullHandler만). 앱이 켜야 보인다:
    logging.basicConfig(level=logging.DEBUG)

모든 줄에 run=/exec=가 붙는다 — 워커가 여럿이면 그것 없이는 줄을 실행 단위로 묶을 수 없다.
"""
from __future__ import annotations

import asyncio
import logging

from strata import Agent
from strata import AgentResult
from strata import ModelResponse
from strata import Provider
from strata import Strategy


class PricedProvider(Provider):
    """child마다 다른 비용 — 어느 가지가 비쌌는지 보이게."""

    def __init__(self):
        self.costs = {'루트 작업': 10, '싼 조각': 5, '비싼 조각': 100}

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')
        return ModelResponse(text=f'{task} 완료', usage={'total_tokens': self.costs[task]})


class SpawnTwo(Strategy):
    async def execute(self, context, runtime):
        if context.metadata.get('execution_id') != 'exec_0':
            await runtime.generate(context)
            return AgentResult(result='child done')
        await runtime.generate(context)
        await runtime.spawn_agent('싼 조각', context)
        await runtime.spawn_agent('비싼 조각', context)
        return AgentResult(result='root done')


def show(node, depth=0):
    subtree = node.subtree_usage()['total_tokens']
    own = node.usage['total_tokens']
    share = f'{subtree / 115:.0%}'
    print(f"{'  ' * depth}{node.id:8} {node.task:12} 직접 {own:>4} · 자손 포함 {subtree:>4} ({share})")
    for child in node.children:
        show(child, depth + 1)


async def main():
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')

    agent = Agent(provider=PricedProvider(), strategy=SpawnTwo())
    result = await agent.run('루트 작업')

    print(f"\nrun_id = {result.metadata['run_id']}   (UUIDv7 — 문자열 정렬 = 시각순)")
    print('\n노드별 토큰 — run 총합만으로는 어느 가지가 비쌌는지 알 수 없다:')
    show(agent.runtime.execution.root)

    root = agent.runtime.execution.root
    assert root.subtree_usage()['total_tokens'] == agent.runtime.usage['total_tokens']
    assert root.children[1].usage['total_tokens'] == 100


if __name__ == '__main__':
    asyncio.run(main())
