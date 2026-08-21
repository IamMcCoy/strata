"""Recursive/RLM 최소 예제 — 외부 API 없이 fake provider로 depth 2 재귀 실행.

실행: uv run python examples/recursive.py

root가 조사를 두 갈래로 분해(spawn)하고, 한 갈래는 다시 심층 조사를 spawn한다.
실행이 끝나면 Execution Tree 전체를 출력한다.
"""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import ModelResponse
from strata import Provider
from strata import RecursiveStrategy
from strata import RuntimeConfig
from strata import ToolCall


def spawn(*tasks):
    return ModelResponse(
        tool_calls=[
            ToolCall(name='spawn_agent', arguments={'task': task}) for task in tasks
        ],
    )


def final(text):
    return ModelResponse(text=text)


class TaskScriptedProvider(Provider):
    """LLM 흉내: task별로 분해 → 하위 결과 종합의 정해진 흐름을 재현."""

    def __init__(self, script):
        self.script = {task: list(responses) for task, responses in script.items()}

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')  # system 지시가 앞에 붙는다
        return self.script[task].pop(0)


def render(node, indent=0):
    result = node.result.result if node.result else ''
    print(f"{'  ' * indent}- [{node.status}] depth={node.depth} {node.task!r} → {result!r}")
    for child in node.children:
        render(child, indent + 1)


async def main():
    provider = TaskScriptedProvider({
        '에이전트 프레임워크 동향 보고서': [
            spawn('오픈소스 프레임워크 조사', '상용 프레임워크 조사'),
            final('보고서: 오픈소스는 조합성, 상용은 관측성에 집중하는 추세다.'),
        ],
        '오픈소스 프레임워크 조사': [
            spawn('RLM 계열 심층 조사'),  # depth 2
            final('오픈소스: 조합 가능한 runtime 지향. RLM 계열이 부상 중.'),
        ],
        '상용 프레임워크 조사': [
            final('상용: 관측성과 비용 제어가 차별점.'),
        ],
        'RLM 계열 심층 조사': [
            final('RLM: 문맥을 환경 변수로 두고 재귀 분해로 처리.'),
        ],
    })

    agent = Agent(provider=provider, strategy=RecursiveStrategy(), config=RuntimeConfig(max_depth=3))

    result = await agent.run('에이전트 프레임워크 동향 보고서')
    print(f'status: {result.status}')
    print(f'result: {result.result}')
    print('\nExecution Tree:')
    render(agent.runtime.execution.root)

    depths = {node.depth for node in agent.runtime.execution.nodes.values()}
    assert result.status == 'completed' and 2 in depths  # Phase 3 완료 기준: depth >= 2


if __name__ == '__main__':
    asyncio.run(main())
