"""ReActStrategy — tool calling loop 검증. 실제 LLM 호출 없음."""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import ModelResponse
from strata import Provider
from strata import ReActStrategy
from strata import Tool
from strata import ToolCall


class AddTool(Tool):
    name = 'add'
    description = 'Add two numbers'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'number'}, 'b': {'type': 'number'}},
    }

    async def execute(self, **kwargs):
        return kwargs['a'] + kwargs['b']


class ScriptedProvider(Provider):
    """정해진 응답을 순서대로 반환하는 fake."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_messages = []

    async def generate(self, messages, tools=None, **kwargs):
        self.seen_messages.append(list(messages))
        return self.responses.pop(0)


def make_agent(provider):
    return Agent(provider=provider, strategy=ReActStrategy(), tools=[AddTool()])


def test_react_tool_loop():
    provider = ScriptedProvider([
        ModelResponse(tool_calls=[ToolCall(name='add', arguments={'a': 1, 'b': 2})]),
        ModelResponse(text='3'),
    ])
    result = asyncio.run(make_agent(provider).run('1 + 2?'))
    assert result.status == 'completed'
    assert result.result == '3'
    # tool 관찰이 다음 provider 호출의 메시지에 포함된다
    observation = provider.seen_messages[-1][-1]
    assert observation['role'] == 'tool'
    assert observation['name'] == 'add'
    assert observation['content'] == '3'


def test_react_unknown_tool_becomes_observation():
    provider = ScriptedProvider([
        ModelResponse(tool_calls=[ToolCall(name='nope', arguments={})]),
        ModelResponse(text='recovered'),
    ])
    result = asyncio.run(make_agent(provider).run('x'))
    assert result.result == 'recovered'
    observation = provider.seen_messages[-1][-1]
    assert observation['role'] == 'tool'
    assert 'not found' in observation['content']


def test_react_hits_iteration_limit():
    tool_call = ModelResponse(tool_calls=[ToolCall(name='add', arguments={'a': 0, 'b': 0})])
    provider = ScriptedProvider([tool_call] * 30)  # max_iterations 기본값과 동일
    result = asyncio.run(make_agent(provider).run('loop'))
    assert result.status == 'budget_exceeded'
