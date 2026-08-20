"""RLM 최소 예제 — 외부 API 없이 fake provider로 "거대 문맥 분할 정복"을 재현한다.

실행: uv run python examples/rlm.py

거대 입력은 메시지가 아니라 변수 `context`로 들어가고(Agent.run(task, context=...)),
모델은 python tool로 조각낸 뒤 llm_query로 child agent에 조각만 넘겨 결과를 변수에 모은다.
실행이 끝나면 Execution Tree를 출력한다.
"""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import ModelResponse
from strata import Provider
from strata import RLMStrategy
from strata import ToolCall

CHAPTERS = [f'제{i}장. ' + f'이 장의 핵심 숫자는 {i * 11}이다. ' * 200 for i in range(1, 6)]
BOOK = '\n'.join(CHAPTERS)  # 모델의 window에 올리지 않을 "거대" 입력


def py(code):
    return ModelResponse(tool_calls=[ToolCall(name='python', arguments={'code': code})])


class ScriptedProvider(Provider):
    """LLM 흉내 — root는 RLM 작업 패턴(inspect → chunk → llm_query → aggregate)을, child는 요약을 수행."""

    def __init__(self):
        self.root_steps = [
            py('print(len(context)); print(context[:40])'),
            py(
                'chapters = context.split("\\n")\n'
                'answers = [llm_query("이 장의 핵심 숫자만 답해라", context=ch) for ch in chapters]\n'
                'print(answers)',
            ),
            py('print(sum(int(a) for a in answers))'),
        ]

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')
        last = messages[-1]
        if task.startswith('이 장의 핵심 숫자'):
            if last['role'] == 'user':  # child: 자기 조각을 python으로 읽는다
                return py('import re; print(re.search(r"핵심 숫자는 (\\d+)", context).group(1))')
            return ModelResponse(text=last['content'].strip())
        if self.root_steps:
            return self.root_steps.pop(0)
        return ModelResponse(text=f"모든 장의 핵심 숫자 합은 {last['content'].strip()}입니다.")


def render(node, indent=0):
    result = node.result.result if node.result else ''
    print(f"{'  ' * indent}- [{node.status}] depth={node.depth} {node.task[:20]!r} → {result!r}")
    for child in node.children:
        render(child, indent + 1)


async def main():
    agent = Agent(provider=ScriptedProvider(), strategy=RLMStrategy(), instructions='한국어로 답하라.')
    result = await agent.run('이 책의 모든 장의 핵심 숫자를 합산하라.', context=BOOK)
    print(f'status: {result.status}')
    print(f'result: {result.result}')
    print('\nExecution Tree:')
    render(agent.runtime.execution.root)

    assert result.status == 'completed'
    assert '165' in result.result  # 11+22+33+44+55
    assert len(agent.runtime.execution.root.children) == len(CHAPTERS)


if __name__ == '__main__':
    asyncio.run(main())
