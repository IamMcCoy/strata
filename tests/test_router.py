"""RouterStrategy — 결정적 규칙 우선, tool call 분류, default 폴백. 실제 LLM 호출 없음."""
from __future__ import annotations

import asyncio

import pytest
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import AgentResult
from strata import ModelResponse
from strata import ReActStrategy
from strata import RLMStrategy
from strata import RouterStrategy
from strata import Strategy
from strata import ToolCall


class Marker(Strategy):
    """어느 전략이 실제로 돌았는지 결과로 말한다."""

    def __init__(self, name, description=''):
        super().__init__()
        self.name = name
        self.description = description
        self.seen_messages = None

    async def execute(self, context, runtime):
        self.seen_messages = list(context.messages)
        return AgentResult(result=self.name)


def route(name):
    return ModelResponse(tool_calls=[ToolCall(name='route', arguments={'strategy': name})])


def run(responses, routes, *, default='a', task='t', context=None, history=None, **kwargs):
    provider = ScriptedProvider(responses)
    agent = Agent(
        provider=provider,
        strategy=RouterStrategy(routes, default=default, **kwargs),
    )
    result = asyncio.run(agent.run(task, context=context, history=history))
    return result, provider


def test_model_choice_selects_the_route():
    a, b = Marker('a'), Marker('b')
    result, provider = run([route('b')], {'a': a, 'b': b})
    assert result.result == 'b' and result.metadata['route'] == 'b'
    assert len(provider.seen) == 1  # 분류 1회. 고른 전략은 generate를 안 쓰는 Marker다


def test_catalog_and_prompt_go_into_the_classification_call():
    a = Marker('a', description='does A things')
    result, provider = run([route('a')], {'a': a, 'b': Marker('b')})
    system = provider.seen[0][0]
    assert system['role'] == 'system'
    assert 'does A things' in system['content']
    assert 'route' in system['content'] or 'strategy' in system['content'].lower()


def test_missing_description_falls_back_to_class_name():
    """커스텀 전략이 description을 몰라도 라우팅에 낀다."""
    router = RouterStrategy({'a': Marker('a'), 'b': Marker('b')}, default='a')
    assert 'Marker' in router.catalog()


def test_huge_input_skips_the_model_entirely():
    """결정적 규칙: variables['context']가 있으면 묻지 않고 rlm으로 간다."""
    rlm = Marker('rlm')
    result, provider = run([], {'a': Marker('a'), 'rlm': rlm}, context='x' * 5000)
    assert result.result == 'rlm' and result.metadata['route'] == 'rlm'
    assert provider.seen == []  # generate 0회


def test_rule_does_not_fire_when_that_route_is_absent():
    result, provider = run([route('a')], {'a': Marker('a'), 'b': Marker('b')}, context='big')
    assert result.metadata['route'] == 'a'
    assert len(provider.seen) == 1  # 규칙이 안 걸려 모델에게 물었다


def test_context_route_can_be_renamed_or_disabled():
    result, _ = run([], {'a': Marker('a'), 'big': Marker('big')}, context='x', context_route='big')
    assert result.metadata['route'] == 'big'
    result, provider = run(
        [route('a')], {'a': Marker('a'), 'rlm': Marker('rlm')},
        context='x', context_route=None,
    )
    assert result.metadata['route'] == 'a' and len(provider.seen) == 1


def test_text_only_reply_falls_back_to_default():
    """모델이 tool call 형식을 못 지키면(실측: Gemma4-12B) 라우팅은 전체 실패가 된다 — default가 막는다."""
    result, _ = run([final('I think reflection would be nice')], {'a': Marker('a'), 'b': Marker('b')})
    assert result.metadata['route'] == 'a'


def test_unknown_route_name_falls_back_to_default():
    result, _ = run([route('nope')], {'a': Marker('a'), 'b': Marker('b')})
    assert result.metadata['route'] == 'a'


def test_chosen_strategy_sees_the_whole_conversation():
    """child로 띄우지 않는 이유 — 라우터를 씌워도 멀티턴이 깨지지 않는다 (ADR-0010)."""
    b = Marker('b')
    history = [{'role': 'user', 'content': '이전 턴'}, {'role': 'assistant', 'content': '이전 답'}]
    run([route('b')], {'a': Marker('a'), 'b': b}, history=history, task='이번 턴')
    assert [m['content'] for m in b.seen_messages] == ['이전 턴', '이전 답', '이번 턴']


def test_default_must_be_one_of_the_routes():
    with pytest.raises(ValueError, match='default'):
        RouterStrategy({'a': Marker('a')}, default='b')
    with pytest.raises(ValueError, match='empty'):
        RouterStrategy({}, default='a')


def test_routes_accept_the_real_strategies():
    """내장 전략들이 실제로 라우팅 대상이 된다 — description이 전부 채워져 있다."""
    router = RouterStrategy(
        {'react': ReActStrategy(), 'rlm': RLMStrategy()}, default='react',
    )
    catalog = router.catalog()
    assert 'tools in a loop' in catalog and 'context window' in catalog


def test_description_is_overridable_per_instance():
    """서브클래싱 없이 생성자로 바꾼다 — 도메인 용어로 다시 쓰는 게 가장 값싼 튜닝이다 (ADR-0009)."""
    router = RouterStrategy(
        {
            'lookup': ReActStrategy(description='단순 조회·계산. 사내 API로 바로 답할 수 있는 질문.'),
            'bulk': RLMStrategy(description='대용량 로그·문서 일괄 처리.'),
        },
        default='lookup',
    )
    catalog = router.catalog()
    assert '- lookup: 단순 조회·계산. 사내 API로 바로 답할 수 있는 질문.' in catalog
    assert '- bulk: 대용량 로그·문서 일괄 처리.' in catalog
    assert 'tools in a loop' not in catalog  # 기본 설명이 남아 있지 않다


def test_overridden_description_reaches_the_model():
    a = ReActStrategy(description='도메인 전용 설명')
    result, provider = run([route('a')], {'a': Marker('a'), 'b': Marker('b')})
    assert result.metadata['route'] == 'a'
    router = RouterStrategy({'a': a}, default='a')
    assert '도메인 전용 설명' in router.catalog()


def test_router_description_is_overridable_too():
    router = RouterStrategy({'a': Marker('a')}, default='a', description='우리 팀 라우터')
    assert router.description == '우리 팀 라우터'


def test_class_default_description_is_not_polluted():
    ReActStrategy(description='일회성')
    assert ReActStrategy().description.startswith('Solve the task directly')
