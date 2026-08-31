"""ReActStrategy — tool calling loop 검증. 실제 LLM 호출 없음."""
from __future__ import annotations

import asyncio

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata.agent import Agent
from strata.strategies import ReActStrategy
from strata.tools import Tool


class AddTool(Tool):
    name = 'add'
    description = 'Add two numbers'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'number'}, 'b': {'type': 'number'}},
    }

    async def execute(self, env, **kwargs):
        return kwargs['a'] + kwargs['b']


def make_agent(provider):
    return Agent(provider=provider, strategy=ReActStrategy(), tools=[AddTool()])


def test_react_tool_loop():
    provider = ScriptedProvider([call('add', a=1, b=2), final('3')])
    result = asyncio.run(make_agent(provider).run('1 + 2?'))
    assert result.status == 'completed'
    assert result.result == '3'
    # tool 관찰이 다음 provider 호출의 메시지에 포함된다
    observation = provider.seen[-1][-1]
    assert observation['role'] == 'tool'
    assert observation['name'] == 'add'
    assert observation['content'] == '3'


def test_react_unknown_tool_becomes_observation():
    provider = ScriptedProvider([call('nope'), final('recovered')])
    result = asyncio.run(make_agent(provider).run('x'))
    assert result.result == 'recovered'
    observation = provider.seen[-1][-1]
    assert observation['role'] == 'tool'
    assert 'not found' in observation['content']


def test_react_hits_iteration_limit():
    provider = ScriptedProvider([call('add', a=0, b=0)] * 30)  # max_iterations 기본값과 동일
    result = asyncio.run(make_agent(provider).run('loop'))
    assert result.status == 'budget_exceeded'


def test_registry_tool_wins_over_strategy_default_tool():
    """default_tools 규칙: 같은 이름이 registry에 있으면 registry 것을 광고하고 중복 광고하지 않는다."""
    class MyAdd(AddTool):
        pass

    class AddByDefault(ReActStrategy):
        default_tools = (AddTool(),)

    provider = ScriptedProvider([final('ok')])
    agent = Agent(provider=provider, strategy=AddByDefault(), tools=[MyAdd()])
    asyncio.run(agent.run('x'))
    advertised = AddByDefault().tools(agent.runtime)
    assert [type(t) for t in advertised] == [MyAdd]
