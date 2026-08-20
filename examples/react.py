"""ReAct 최소 예제 — 외부 API 없이 fake provider로 end-to-end 실행.

실행: uv run python examples/react.py

실제 Provider(OpenAI 등)를 붙이면 ScriptedProvider 자리만 교체하면 된다 —
Strategy와 Tool은 그대로다.
"""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import ModelResponse
from strata import Provider
from strata import ReActStrategy
from strata import Tool
from strata import ToolCall


class MultiplyTool(Tool):
    name = 'multiply'
    description = 'Multiply two numbers'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'number'}, 'b': {'type': 'number'}},
        'required': ['a', 'b'],
    }

    async def execute(self, **kwargs):
        return kwargs['a'] * kwargs['b']


class ScriptedProvider(Provider):
    """LLM 흉내: tool을 한 번 호출한 뒤 관찰을 인용해 답한다."""

    async def generate(self, messages, tools=None, **kwargs):
        last = messages[-1]
        if last['role'] == 'user':
            return ModelResponse(
                tool_calls=[ToolCall(name='multiply', arguments={'a': 12, 'b': 34})],
            )
        return ModelResponse(text=f"계산 결과는 {last['content']}입니다.")


async def main():
    agent = Agent(
        provider=ScriptedProvider(),
        strategy=ReActStrategy(),
        tools=[MultiplyTool()],
    )
    result = await agent.run('12 곱하기 34는?')
    print(f'status: {result.status}')
    print(f'result: {result.result}')
    assert result.result == '계산 결과는 408입니다.'


if __name__ == '__main__':
    asyncio.run(main())
