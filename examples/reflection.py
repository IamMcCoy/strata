"""Reflection 최소 예제 — 외부 API 없이 fake provider로 초안 → 비판 → 수정 2라운드.

실행: uv run python examples/reflection.py

초안·비판·수정이 전부 별도 child agent로 뜬다. 비판자가 초안을 쓴 대화를 보지 못하는 것이
이 패턴의 핵심이다 — 자기 초안에 물든 문맥 안에서 하는 비판은 비판이 아니다.
실행이 끝나면 Execution Tree에 child 5개(초안 1 + (비판+수정) × 2)가 남는다.
"""
from __future__ import annotations

import asyncio

from strata.agent import Agent
from strata.providers import ModelResponse
from strata.providers import Provider
from strata.strategies import ReflectionStrategy

DRAFTS = [
    '저희는 좋은 회사입니다. 최고의 기술로 최고의 서비스를 제공합니다.',
    '저희는 2019년 설립된 에이전트 인프라 회사로, 국내 12개 기업의 운영 자동화를 맡고 있습니다.',
    '2019년 설립. 에이전트 실행 인프라를 만들고, 국내 12개 기업의 운영 자동화를 맡고 있습니다. '
    '평균 처리 시간을 40% 줄였습니다.',
]

CRITIQUES = [
    '1) "좋은", "최고의"는 근거 없는 자평이다 — 검증 가능한 사실로 바꿔라. '
    '2) 무엇을 만드는 회사인지가 없다. 3) 규모·연혁이 전혀 없다.',
    '1) 설립연도와 고객 수는 들어왔으나 성과 수치가 없다. 2) 문장이 한 덩어리라 읽기 어렵다.',
]


class ScriptedProvider(Provider):
    """LLM 흉내: 어떤 child로 떠 있는지를 task 첫 줄로 구분해 응답한다."""

    def __init__(self) -> None:
        self.revisions = 0

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')
        if task.startswith('Critique'):
            return ModelResponse(text=CRITIQUES[self.revisions])
        if task.startswith('Rewrite'):
            self.revisions += 1
            return ModelResponse(text=DRAFTS[self.revisions])
        return ModelResponse(text=DRAFTS[0])


def render(node, indent=0):
    result = node.result.result if node.result else ''
    print(f"{'  ' * indent}- [{node.status}] {node.task.splitlines()[0]!r} → {result[:40]!r}")
    for child in node.children:
        render(child, indent + 1)


async def main():
    agent = Agent(provider=ScriptedProvider(), strategy=ReflectionStrategy(rounds=2))

    result = await agent.run('회사 소개 문단을 써줘')
    print(f'status: {result.status} (rounds={result.metadata["rounds_completed"]})')
    print(f'result: {result.result}\n')
    for index, round_ in enumerate(result.evidence, start=1):
        print(f'[round {index}] 비판: {round_["critique"]}')
        print(f'[round {index}] 수정: {round_["draft"]}\n')

    print('Execution Tree:')
    render(agent.runtime.execution.root)

    # Phase 7 완료 기준: 라운드가 실제로 돌고, 초안·비판·수정이 모두 child로 떴다
    assert result.result == DRAFTS[2]
    assert len(agent.runtime.execution.root.children) == 5


if __name__ == '__main__':
    asyncio.run(main())
