"""Runtime primitive(generate/execute_tool/spawn_agent)가 한도·지시·회복 규칙을 강제하는지 검증. LLM 호출 없음."""
from __future__ import annotations

import asyncio

from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import AgentResult
from strata import ModelResponse
from strata import Provider
from strata import ReActStrategy
from strata import RecursiveStrategy
from strata import RuntimeConfig
from strata import Strategy
from strata import Tool
from strata import ToolCall


class BoomTool(Tool):
    name = 'boom'
    description = 'always raises'
    input_schema = {'type': 'object', 'properties': {}}

    async def execute(self, env, **kwargs):
        raise RuntimeError('kaboom')


def test_instructions_become_system_message():
    provider = ScriptedProvider([final('hi')])
    agent = Agent(provider=provider, strategy=ReActStrategy(), instructions='Be terse.')
    asyncio.run(agent.run('hello'))
    assert provider.seen[0][0] == {'role': 'system', 'content': 'Be terse.'}
    assert provider.seen[0][1] == {'role': 'user', 'content': 'hello'}


def test_no_instructions_means_no_system_message():
    provider = ScriptedProvider([final('hi')])
    asyncio.run(Agent(provider=provider, strategy=ReActStrategy()).run('hello'))
    assert provider.seen[0][0]['role'] == 'user'


def test_max_iterations_enforced_by_runtime_even_for_custom_strategy():
    class ForeverStrategy(Strategy):  # max_iterations를 전혀 모르는 Custom Strategy
        async def execute(self, context, runtime):
            while True:
                response = await runtime.generate(context)
                context.messages.append({'role': 'assistant', 'content': response.text})

    provider = ScriptedProvider([final(f'step {i}') for i in range(10)])
    agent = Agent(provider=provider, strategy=ForeverStrategy(), config=RuntimeConfig(max_iterations=3))
    result = asyncio.run(agent.run('loop'))
    assert result.status == 'budget_exceeded'
    assert result.metadata['reason'] == 'max_iterations'
    assert result.result == 'step 2'  # 지금까지의 마지막 답을 담는다
    assert len(provider.seen) == 3


def test_token_budget_accumulates_across_run():
    spend_60 = ModelResponse(tool_calls=[ToolCall(name='nope', arguments={})], usage={'total_tokens': 60})
    provider = ScriptedProvider([spend_60, spend_60, final('never')])
    agent = Agent(provider=provider, strategy=ReActStrategy(), config=RuntimeConfig(token_budget=100))
    result = asyncio.run(agent.run('spend'))
    assert result.status == 'budget_exceeded'
    assert result.metadata['reason'] == 'token_budget'
    assert agent.runtime.usage['total_tokens'] == 120
    assert len(provider.seen) == 2  # 3번째 호출은 예산 검사에서 차단


def test_timeout_returns_contract():
    class SlowProvider(Provider):
        async def generate(self, messages, tools=None, **kwargs):
            await asyncio.sleep(1)
            return ModelResponse(text='late')

    agent = Agent(provider=SlowProvider(), strategy=ReActStrategy(), config=RuntimeConfig(timeout=0.05))
    result = asyncio.run(agent.run('slow'))
    assert result.status == 'budget_exceeded'
    assert result.metadata['reason'] == 'timeout'
    assert agent.runtime.execution.root.status == 'budget_exceeded'


def test_tool_exception_becomes_observation():
    provider = ScriptedProvider([call('boom'), final('recovered')])
    agent = Agent(provider=provider, strategy=ReActStrategy(), tools=[BoomTool()])
    result = asyncio.run(agent.run('x'))
    assert result.result == 'recovered'
    observation = provider.seen[-1][-1]
    assert observation['role'] == 'tool'
    assert 'kaboom' in observation['content']


def test_child_inherits_instructions_and_receives_sub_context():
    provider = ScriptedProvider([
        call('spawn_agent', task='child task', context='CHUNK'),  # root
        final('child done'),                                       # child
        final('root done'),                                        # root
    ])
    captured = {}

    class ProbeStrategy(RecursiveStrategy):
        async def execute(self, context, runtime):
            if context.metadata['task'] == 'child task':
                captured['variables'] = dict(context.variables)
                captured['instructions'] = context.instructions
            return await super().execute(context, runtime)

    agent = Agent(provider=provider, strategy=ProbeStrategy(), instructions='SYS')
    result = asyncio.run(agent.run('root'))
    assert result.result == 'root done'
    assert captured == {'variables': {'context': 'CHUNK'}, 'instructions': 'SYS'}
    # child의 system 메시지도 상속된 지시로 조립된다
    child_call = provider.seen[1]
    assert child_call[0] == {'role': 'system', 'content': 'SYS'}
    assert child_call[1] == {'role': 'user', 'content': 'child task'}


def test_child_budget_exceeded_carries_partial_result_to_parent():
    provider = ScriptedProvider([
        call('spawn_agent', task='child'),                                # root
        ModelResponse(text='thinking...', tool_calls=[ToolCall(name='nope', arguments={})]),  # child 1
        ModelResponse(text='still', tool_calls=[ToolCall(name='nope', arguments={})]),        # child 2
        final('root done'),                                                # root
    ])
    agent = Agent(provider=provider, strategy=RecursiveStrategy(), config=RuntimeConfig(max_iterations=2))
    result = asyncio.run(agent.run('root'))
    assert result.status == 'completed'
    (child,) = agent.runtime.execution.root.children
    assert child.status == 'budget_exceeded'
    assert child.result == AgentResult(
        status='budget_exceeded', result='still', metadata={'reason': 'max_iterations', 'limit': 2},
    )
    observation = provider.seen[-1][-1]['content']
    assert 'budget_exceeded' in observation and 'still' in observation
