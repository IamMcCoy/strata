"""RLMStrategy + PythonTool: 변수 환경, REPL 상태 유지, llm_query 재귀, 회복. LLM 호출 없음."""
from __future__ import annotations

import asyncio

from conftest import call
from conftest import final
from conftest import TaskScriptedProvider
from strata import Agent
from strata import PythonTool
from strata import RLMStrategy
from strata import RuntimeConfig


def py(code):
    return call('python', code=code)


def run(script, task, context=None, **agent_kwargs):
    provider = TaskScriptedProvider(script)
    agent = Agent(provider=provider, strategy=RLMStrategy(), **agent_kwargs)
    return asyncio.run(agent.run(task, context=context)), provider, agent


def test_context_is_a_variable_not_a_message_and_state_persists():
    big = 'x' * 5000
    result, provider, _ = run(
        {
            'count': [py('n = len(context)'), py('print(n, context[:3])'), final('done')],
        }, 'count', context=big,
    )
    assert result.result == 'done'
    # 메시지에는 거대 입력이 없고 system 지시에 변수 설명만 있다
    _, first_call = provider.seen[0]
    assert all(big not in (m.get('content') or '') for m in first_call)
    assert first_call[0]['role'] == 'system'
    assert '- context: str, len=5000' in first_call[0]['content']
    assert 'llm_query' in first_call[0]['content']
    # 두 번째 호출이 첫 호출의 변수 n을 본다 — REPL 상태 유지
    assert provider.observations('count')[-1] == '5000 xxx\n'
    # 두 번째 호출의 system에는 새 변수 n이 나타나고, 주입된 helper(llm_query/print)는 변수로 노출되지 않는다
    _, second_call = provider.seen[1]
    assert '- n: int' in second_call[0]['content']
    assert '- llm_query' not in second_call[0]['content'] and '- print' not in second_call[0]['content']


def test_llm_query_spawns_child_with_sub_context():
    result, provider, agent = run(
        {
            'root': [
                py(
                    'chunks = [context[i:i+2] for i in range(0, len(context), 2)]\n'
                    'answers = [llm_query("summarize", context=c) for c in chunks]\n'
                    'print(answers)',
                ),
                final('aggregated'),
            ],
            'summarize': [final('s1'), final('s2'), final('s3')],
        }, 'root', context='aabbcc',
    )
    assert result.result == 'aggregated'
    assert provider.observations('root')[-1] == "['s1', 's2', 's3']\n"
    children = agent.runtime.execution.root.children
    assert [c.task for c in children] == ['summarize'] * 3
    # 각 child는 자기 조각만 변수로 받고, 부모의 지시(RLM env 설명)를 포함한 system을 받는다
    child_calls = [msgs for task, msgs in provider.seen if task == 'summarize']
    assert all('- context: str, len=2' in msgs[0]['content'] for msgs in child_calls)


def test_llm_query_reports_refused_spawn_instead_of_raising():
    result, provider, _ = run(
        {
            'root': [py('print(llm_query("x"))'), final('ok')],
        }, 'root', config=RuntimeConfig(max_depth=0),
    )
    assert result.result == 'ok'
    assert 'budget_exceeded' in provider.observations('root')[-1]


def test_repl_echoes_trailing_expression_like_jupyter():
    result, provider, _ = run(
        {
            'root': [py('chapters = context.split(",")\nlen(chapters)'), py('chapters[:2]'), py('x = 1'), final('ok')],
        }, 'root', context='a,b,c',
    )
    assert result.result == 'ok'
    assert provider.observations('root') == ['3\n', "['a', 'b']\n", '(no output)']


def test_python_exception_and_output_truncation_become_observations():
    result, provider, _ = run(
        {
            'root': [py('1/0'), py('print("y" * 50_000)'), py('def f(:\n  pass'), final('ok')],
        }, 'root',
    )
    assert result.result == 'ok'
    observations = provider.observations('root')
    assert observations[0] == (
        'Traceback (most recent call last):\n  File "<python>", line 1, in <module>\n'
        'ZeroDivisionError: division by zero\n'
    )
    assert observations[1].endswith('[truncated, 50001 chars total]')
    assert len(observations[1]) < 11_000
    assert observations[2].startswith('  File "<python>", line 1') and 'SyntaxError' in observations[2]
    assert 'strata/tools/python.py' not in observations[0] + observations[2]


def test_user_registered_python_tool_wins_over_default():
    class SandboxPython(PythonTool):
        async def execute(self, env, code='', **kwargs):
            return 'sandboxed'

    result, provider, _ = run(
        {'root': [py('anything'), final('ok')]}, 'root', tools=[SandboxPython()],
    )
    assert provider.observations('root')[-1] == 'sandboxed'
    assert result.result == 'ok'
