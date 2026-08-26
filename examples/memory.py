"""Memory 최소 예제 — 두 번의 실행 사이에 정보가 남는다 (Phase 4).

실행: uv run python examples/memory.py

실행 A: 모델이 remember tool로 사실 하나를 저장한다.
실행 B: 같은 Memory를 가진 새 run이 task로 조회한 결과를 system 지시로 받는다.
"""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import InMemory
from strata import MemoryTool
from strata import ModelResponse
from strata import Provider
from strata import ReActStrategy
from strata import ToolCall

FACT = '사용자는 패키지 관리에 uv를 쓴다'


class ScriptedProvider(Provider):
    """LLM 흉내: 기억할 게 있으면 저장하고, 없으면 받은 system 지시를 그대로 인용한다."""

    async def generate(self, messages, tools=None, **kwargs):
        last, system = messages[-1], messages[0]['content'] if messages[0]['role'] == 'system' else ''
        if last['role'] == 'user' and '기억해' in last['content']:
            return ModelResponse(tool_calls=[ToolCall(name='remember', arguments={'content': FACT})])
        if last['role'] == 'tool':
            return ModelResponse(text=f"저장했습니다 — {last['content']}")
        if FACT in system:
            return ModelResponse(text=f'기억하고 있습니다: {FACT}')
        return ModelResponse(text='기억나는 게 없습니다.')


async def main():
    memory = InMemory()

    def agent():  # 실행마다 새 Agent — 공유되는 건 Memory뿐
        return Agent(
            provider=ScriptedProvider(), strategy=ReActStrategy(),
            tools=[MemoryTool()], memory=memory,
        )

    a = await agent().run('앞으로 uv를 쓴다는 걸 기억해')
    print(f'run A: {a.result}  → 저장된 항목 {len(memory.items)}개')

    b = await agent().run('패키지 설치는 어떻게 하지?')
    print(f'run B: {b.result}')
    assert FACT in (b.result or '')


if __name__ == '__main__':
    asyncio.run(main())
