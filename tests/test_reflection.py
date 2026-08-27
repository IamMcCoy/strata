"""ReflectionStrategy — 초안 → 비판 → 수정 라운드 + spawn_agent(strategy=) 검증. 실제 LLM 호출 없음."""
from __future__ import annotations

import asyncio

from conftest import final
from strata import Agent
from strata import AgentResult
from strata import Provider
from strata import REFLECTION_CRITIC_PROMPT
from strata import ReflectionStrategy
from strata import RuntimeConfig
from strata import Strategy


class ReflectionProvider(Provider):
    """초안 → 비판 → 수정 흐름을 재현. 수정본에 번호를 붙여 몇 라운드 돌았는지 결과로 보이게 한다."""

    def __init__(self) -> None:
        self.tasks: list[str] = []
        self.systems: list[str | None] = []
        self.revisions = 0

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')
        self.tasks.append(task)
        self.systems.append(messages[0]['content'] if messages[0]['role'] == 'system' else None)
        if task.startswith('Critique'):
            return final(f'critique of draft v{self.revisions + 1}')
        if task.startswith('Rewrite'):
            self.revisions += 1
            return final(f'draft v{self.revisions + 1}')
        return final('draft v1')


def run_agent(rounds=2, *, instructions=None, worker=None, **config_kwargs):
    provider = ReflectionProvider()
    agent = Agent(
        provider=provider,
        strategy=ReflectionStrategy(rounds=rounds, worker=worker),
        instructions=instructions,
        config=RuntimeConfig(**config_kwargs),
    )
    result = asyncio.run(agent.run('원본 과제'))
    return result, agent.runtime, provider


def test_rounds_produce_the_final_revision():
    result, _, provider = run_agent(rounds=2)
    assert result.status == 'completed'
    assert result.result == 'draft v3'  # 초안 + 2회 수정
    assert result.metadata['rounds_completed'] == 2
    # child 5개 = 초안 1 + (비판 + 수정) * 2
    assert len(provider.tasks) == 5


def test_evidence_records_each_round():
    result, _, _ = run_agent(rounds=2)
    assert result.evidence == [
        {'critique': 'critique of draft v1', 'draft': 'draft v2'},
        {'critique': 'critique of draft v2', 'draft': 'draft v3'},
    ]


def test_rounds_zero_returns_the_draft_untouched():
    result, runtime, provider = run_agent(rounds=0)
    assert result.result == 'draft v1'
    assert result.metadata['rounds_completed'] == 0
    assert len(runtime.execution.root.children) == 1


def test_children_run_the_worker_strategy_not_reflection():
    """spawn_agent(strategy=) 미지정이면 child가 ReflectionStrategy를 상속해 무한 재귀한다 (ADR-0006).

    worker를 명시적으로 넘기는지 확인 — Phase 8(전략 조합)의 완료 기준이기도 하다.
    """
    class Recording(Strategy):
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, context, runtime):
            self.calls += 1
            response = await runtime.generate(context)
            return AgentResult(result=response.text)

    worker = Recording()
    result, runtime, _ = run_agent(rounds=1, worker=worker)
    assert worker.calls == 3  # 초안 + 비판 + 수정
    assert result.result == 'draft v2'
    # 모든 child가 root 바로 아래 — reflection이 자기 자신으로 재귀하지 않았다
    assert [node.depth for node in runtime.execution.root.children] == [1, 1, 1]


def test_critic_keeps_user_instructions():
    _, _, provider = run_agent(rounds=1, instructions='USER')
    critic_system = next(
        system for task, system in zip(provider.tasks, provider.systems) if task.startswith('Critique')
    )
    assert critic_system.startswith('USER')
    assert REFLECTION_CRITIC_PROMPT in critic_system


def test_limit_mid_loop_keeps_the_best_draft_so_far():
    """max_children에 걸려도 예외가 아니라 지금까지의 최선으로 끝난다 (불변식 3)."""
    # child 3개까지: 초안 + 비판 + 수정 = 1라운드. 2라운드의 비판이 4번째라 budget_exceeded.
    result, _, _ = run_agent(rounds=2, max_children=3)
    assert result.status == 'completed'
    assert result.result == 'draft v2'
    assert result.metadata['rounds_completed'] == 1


def test_transcript_carries_only_the_latest_draft():
    """멀티턴으로 되돌려 줄 messages에 중간 초안이 쌓이지 않는다 (ADR-0010)."""
    result, _, _ = run_agent(rounds=2)
    messages = result.metadata['messages']
    assert [m['role'] for m in messages] == ['user', 'assistant']
    assert messages[-1]['content'] == 'draft v3'
