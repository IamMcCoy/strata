"""RecursiveStrategy + spawn_agent + Execution Tree 검증. 실제 LLM 호출 없음."""
from __future__ import annotations

import asyncio

from conftest import final
from conftest import TaskScriptedProvider
from strata import Agent
from strata import ModelResponse
from strata import RecursiveStrategy
from strata import RuntimeConfig
from strata import ToolCall


def spawn(*tasks):
    return ModelResponse(tool_calls=[ToolCall(name='spawn_agent', arguments={'task': t}) for t in tasks])


def run_agent(script, **config_kwargs):
    provider = TaskScriptedProvider(script)
    agent = Agent(provider=provider, strategy=RecursiveStrategy(), config=RuntimeConfig(**config_kwargs))
    result = asyncio.run(agent.run('root'))
    return result, agent.runtime, provider


def test_depth_two_recursion_records_full_tree():
    result, runtime, _ = run_agent({
        'root': [spawn('mid'), final('root done')],
        'mid': [spawn('leaf'), final('mid done')],
        'leaf': [final('leaf done')],
    })
    assert result.status == 'completed'
    assert result.result == 'root done'

    root = runtime.execution.root
    assert (root.task, root.depth, root.status) == ('root', 0, 'completed')
    (mid,) = root.children
    assert (mid.task, mid.depth, mid.status) == ('mid', 1, 'completed')
    (leaf,) = mid.children
    assert (leaf.task, leaf.depth, leaf.status) == ('leaf', 2, 'completed')
    assert leaf.result.result == 'leaf done'


def test_max_depth_refuses_spawn_as_contract():
    result, runtime, provider = run_agent(
        {
            'root': [spawn('mid'), final('root done')],
            'mid': [spawn('leaf'), final('mid done')],  # leaf spawn은 거부되어야 함
        }, max_depth=1,
    )
    assert result.status == 'completed'  # 거부가 실행 전체를 죽이지 않는다
    assert len(runtime.execution.nodes) == 2  # root + mid — leaf 노드는 생기지 않음
    assert any('budget_exceeded' in content for content in provider.observations('mid'))


def test_max_children_limits_siblings():
    result, runtime, provider = run_agent(
        {
            'root': [spawn('a', 'b'), final('root done')],
            'a': [final('a done')],  # 'b'는 거부되어 실행되지 않음
        }, max_children=1,
    )
    assert result.status == 'completed'
    assert len(runtime.execution.root.children) == 1
    assert any('budget_exceeded' in content for content in provider.observations('root'))


def test_child_failure_becomes_contract_not_exception():
    result, runtime, provider = run_agent({
        'root': [spawn('boom'), final('root done')],
        'boom': [],  # 응답 소진 → child 내부에서 예외 발생
    })
    assert result.status == 'completed'  # parent는 살아서 완주
    (boom,) = runtime.execution.root.children
    assert boom.status == 'failed'
    assert any('"status": "failed"' in content for content in provider.observations('root'))


def test_each_run_gets_a_fresh_runtime():
    """Runtime은 run당 하나(ADR-0006): 같은 Agent를 두 번 돌려도 usage·tree가 섞이지 않는다."""
    provider = TaskScriptedProvider({'root': [final('one'), final('two')]})
    agent = Agent(provider=provider, strategy=RecursiveStrategy())
    asyncio.run(agent.run('root'))
    first = agent.runtime
    asyncio.run(agent.run('root'))
    assert agent.runtime is not first
    assert len(agent.runtime.execution.nodes) == 1
