"""전략별 한도(Strategy.limits) — 전략이 제안하고 사용자가 이긴다 (ADR-0014). 실제 LLM 호출 없음."""
from __future__ import annotations

import asyncio

import pytest
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import AgentResult
from strata import ReActStrategy
from strata import RecursiveStrategy
from strata import ReflectionStrategy
from strata import RuntimeConfig
from strata import Strategy


class ProbeStrategy(Strategy):
    """실행 시점에 Runtime이 실제로 쓰는 config를 그대로 결과에 싣는다."""

    async def execute(self, context, runtime):
        return AgentResult(result='ok', metadata={'config': runtime.config})


def config_of(strategy, config=None):
    agent = Agent(provider=ScriptedProvider([final('ok')]), strategy=strategy, config=config)
    return asyncio.run(agent.run('t')).metadata['config']


def test_strategy_fills_limits_the_user_did_not_set():
    class Probe(ProbeStrategy):
        pass

    assert config_of(Probe(max_iterations=3)).max_iterations == 3


def test_user_config_beats_the_strategy():
    class Probe(ProbeStrategy):
        pass

    resolved = config_of(Probe(max_iterations=3), RuntimeConfig(max_iterations=7))
    assert resolved.max_iterations == 7


def test_untouched_limits_keep_their_defaults():
    class Probe(ProbeStrategy):
        pass

    resolved = config_of(Probe(max_iterations=3))
    assert (resolved.max_depth, resolved.max_children) == (5, 8)


def test_unknown_limit_fails_at_construction():
    with pytest.raises(TypeError, match='max_iteration'):
        ReActStrategy(max_iteration=3)  # 오타 — run까지 끌고 가지 않는다


def test_none_limit_is_ignored():
    assert ReActStrategy(max_iterations=None).limits == {}


def test_react_family_takes_its_own_limits():
    """루프·재귀 한도를 전략에 붙여 준다 — 사용자가 RuntimeConfig를 따로 만들 필요가 없다."""
    assert ReActStrategy(max_iterations=10).limits == {'max_iterations': 10}
    assert RecursiveStrategy(max_depth=2, max_children=3).limits == {'max_depth': 2, 'max_children': 3}


def test_class_default_limits_are_not_shared():
    ReActStrategy(max_iterations=10)
    assert ReActStrategy().limits == {}  # 클래스 기본값(읽기 전용)이 오염되지 않았다


def test_reflection_proposes_the_children_its_rounds_need():
    """rounds에서 나오는 공식(1 + rounds*2)을 사용자가 알아내 옮겨 적지 않아도 된다."""
    assert ReflectionStrategy(rounds=4).limits == {'max_children': 9}
    # 명시적으로 준 값이 공식을 이긴다
    assert ReflectionStrategy(rounds=4, max_children=3).limits == {'max_children': 3}


def test_derived_limit_only_raises_never_tightens():
    """회귀: 파생 한도는 하한이다.

    rounds=2는 child 5개면 되지만, 그렇다고 max_children을 8→5로 내리면 한도가 run 전체
    공유이므로 worker(Recursive 등)가 재귀 위임에 쓸 자식 수까지 같이 조여진다.
    """
    assert ReflectionStrategy(rounds=0).limits == {}
    assert ReflectionStrategy(rounds=2).limits == {}
    agent = Agent(
        provider=ScriptedProvider([final('ok')]),
        strategy=ReflectionStrategy(rounds=2, worker=ProbeStrategy()),
    )
    asyncio.run(agent.run('t'))
    assert agent.runtime.config.max_children == 8  # worker가 쓸 여유가 깎이지 않았다


def test_reflection_rounds_four_now_completes():
    """회귀: 기본 max_children=8 아래에서는 4라운드가 2라운드 만에 조용히 잘렸다."""
    class Provider(ScriptedProvider):
        def __init__(self):
            super().__init__([])
            self.revisions = 0

        async def generate(self, messages, tools=None, **kwargs):
            task = next(m['content'] for m in messages if m['role'] == 'user')
            if task.startswith('Critique'):
                return final('critique')
            if task.startswith('Rewrite'):
                self.revisions += 1
                return final(f'draft v{self.revisions + 1}')
            return final('draft v1')

    agent = Agent(provider=Provider(), strategy=ReflectionStrategy(rounds=4))
    result = asyncio.run(agent.run('t'))
    assert result.metadata['rounds_completed'] == 4
    assert result.result == 'draft v5'


def test_description_and_limits_are_both_constructor_arguments():
    """둘 다 명시 인자로 받는다 — 오타는 생성 시점 TypeError (ADR-0009)."""
    strategy = ReActStrategy(description='한 줄 설명', max_iterations=5)
    assert strategy.description == '한 줄 설명'
    assert strategy.limits == {'max_iterations': 5}
    with pytest.raises(TypeError, match='descriptoin'):
        ReActStrategy(descriptoin='오타')
