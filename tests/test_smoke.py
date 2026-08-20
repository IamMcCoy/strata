"""Phase 1 스모크 테스트: abstraction들이 조합·실행 가능한지만 확인한다."""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import AgentResult
from strata import Context
from strata import ExecutionNode
from strata import MemoryItem
from strata import ModelResponse
from strata import Provider
from strata import RuntimeConfig
from strata import Strategy


class FakeProvider(Provider):
    async def generate(self, messages, tools=None, **kwargs):
        return ModelResponse(text='ok', usage={'total_tokens': 1})


class FakeStrategy(Strategy):
    async def execute(self, context, runtime):
        response = await runtime.generate(context)
        return AgentResult(result=response.text)


def test_agent_delegates_to_strategy():
    agent = Agent(provider=FakeProvider(), strategy=FakeStrategy())
    result = asyncio.run(agent.run('smoke test'))
    assert result.status == 'completed'
    assert result.result == 'ok'


def test_value_objects():
    assert Context().messages == []
    assert RuntimeConfig().max_depth == 5
    assert ExecutionNode(id='root').status == 'running'
    assert MemoryItem(content='fact').type == 'semantic'


if __name__ == '__main__':
    test_agent_delegates_to_strategy()
    test_value_objects()
    print('smoke ok')
