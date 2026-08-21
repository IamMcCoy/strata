"""Strategy의 prompt(패턴 지시)·environment(현재 상태)·model_params(샘플링 파라미터) 규칙. LLM 호출 없음.

- system = instructions(사용자) + prompt(전략 고정 텍스트) + environment(호출 시점 상태, RLM의 변수 목록).
- prompt: 클래스 기본값 → `prompt=` 인자로 교체, `prompt=''`로 끔. 고정 텍스트 — 템플릿 아님.
- model_params: Runtime.generate가 `{**provider.model_params, **호출 kwargs}`로 합친다 — Strategy가 이긴다.
"""
from __future__ import annotations

import asyncio

import pytest
from conftest import final
from conftest import ScriptedProvider
from strata import Agent
from strata import OpenAIProvider
from strata import REACT_PROMPT
from strata import ReActStrategy
from strata import RECURSIVE_PROMPT
from strata import RLM_PROMPT
from strata import RLMStrategy


def system_of(provider, agent, task='hi'):
    asyncio.run(agent.run(task))
    first = provider.seen[0][0]
    return first['content'] if first['role'] == 'system' else None


# ---- prompt --------------------------------------------------------------------------

def test_prompt_argument_replaces_class_default():
    provider = ScriptedProvider([final('ok')])
    agent = Agent(provider=provider, strategy=ReActStrategy(prompt='CUSTOM'), instructions='USER')
    assert system_of(provider, agent) == 'USER\n\nCUSTOM'


def test_empty_prompt_disables_strategy_prompt():
    provider = ScriptedProvider([final('ok')])
    agent = Agent(provider=provider, strategy=ReActStrategy(prompt=''), instructions='USER')
    assert system_of(provider, agent) == 'USER'


def test_nothing_to_say_means_no_system_message():
    """prompt='' + 사용자 지시 없음 + environment 없음 → system 메시지 자체가 없다(빈 system 금지)."""
    provider = ScriptedProvider([final('ok')])
    assert system_of(provider, Agent(provider=provider, strategy=ReActStrategy(prompt=''))) is None
    assert provider.seen[0][0]['role'] == 'user'


def test_subclass_without_super_init_still_works():
    """기존(이 변경 전) 서브클래스는 __init__이 없었다 — super().__init__()을 안 불러도 깨지지 않아야 한다."""
    class Legacy(ReActStrategy):
        def __init__(self):
            self.calls = 0

    provider = ScriptedProvider([final('ok')])
    result = asyncio.run(Agent(provider=provider, strategy=Legacy()).run('hi'))
    assert result.result == 'ok'
    assert provider.kwargs == [{}]


def test_rlm_environment_survives_objects_whose_len_raises():
    """모델이 REPL에서 만든 이상한 객체 때문에 system 조립(하네스)이 죽으면 안 된다 — 크기만 생략한다."""
    class Weird:
        def __len__(self):
            raise RuntimeError('no len for you')

    provider = ScriptedProvider([final('ok')])
    agent = Agent(provider=provider, strategy=RLMStrategy())
    captured = {}

    class Probe(RLMStrategy):
        async def execute(self, context, runtime):
            context.variables['weird'] = Weird()
            captured['env'] = self.environment(context)
            return await super().execute(context, runtime)

    agent.strategy = Probe()
    asyncio.run(agent.run('hi'))
    assert '- weird: Weird' in captured['env']


def test_subclass_can_override_prompt_as_class_attribute():
    class Quiet(ReActStrategy):
        prompt = 'QUIET'

    provider = ScriptedProvider([final('ok')])
    assert system_of(provider, Agent(provider=provider, strategy=Quiet())) == 'QUIET'


def test_each_strategy_ships_harness_prompt():
    """기본 prompt는 공통(ReAct) 규칙 위에 패턴별 규칙을 얹는다 — 종료 규약·위임 규칙·REPL 규칙."""
    assert 'without calling any tool' in REACT_PROMPT           # 종료 규약
    assert REACT_PROMPT in RECURSIVE_PROMPT and 'spawn_agent' in RECURSIVE_PROMPT
    assert 'does not see this conversation' in RECURSIVE_PROMPT  # child 격리
    assert 'budget_exceeded' in RECURSIVE_PROMPT                 # 한도 관찰 처리
    assert REACT_PROMPT in RLM_PROMPT and 'llm_query' in RLM_PROMPT


def test_rlm_system_is_instructions_then_prompt_then_live_variables():
    """prompt는 고정 텍스트 그대로(export 상수 == 모델이 보는 텍스트), 변수 목록은 environment로 뒤에 붙는다."""
    provider = ScriptedProvider([final('ok')])
    agent = Agent(provider=provider, strategy=RLMStrategy(), instructions='USER')
    asyncio.run(agent.run('go', context='abc'))
    system = provider.seen[0][0]['content']
    assert system.startswith(f'USER\n\n{RLM_PROMPT}\n\n')
    assert system.endswith('- context: str, len=3')


def test_environment_hook_is_appended_after_prompt():
    class Stateful(ReActStrategy):
        prompt = 'RULES'

        def environment(self, context):
            return f'state={context.metadata["task"]}'

    provider = ScriptedProvider([final('ok')])
    assert system_of(provider, Agent(provider=provider, strategy=Stateful()), task='T') == 'RULES\n\nstate=T'


# ---- model_params ----------------------------------------------------------------------

def test_strategy_model_params_reach_provider_on_every_call():
    provider = ScriptedProvider([final('ok')])
    agent = Agent(provider=provider, strategy=ReActStrategy(model_params={'temperature': 0, 'top_p': 0.9}))
    asyncio.run(agent.run('hi'))
    assert provider.kwargs == [{'temperature': 0, 'top_p': 0.9}]


def test_no_model_params_sends_nothing_extra():
    provider = ScriptedProvider([final('ok')])
    asyncio.run(Agent(provider=provider, strategy=ReActStrategy()).run('hi'))
    assert provider.kwargs == [{}]


def test_runtime_merges_provider_defaults_under_strategy_params():
    """우선순위는 Runtime.generate 한 곳: {**provider.model_params, **호출 kwargs}. 어떤 Provider든 동일."""
    provider = ScriptedProvider([final('ok')])
    provider.model_params = {'temperature': 0.7, 'max_tokens': 10}
    agent = Agent(provider=provider, strategy=ReActStrategy(model_params={'temperature': 0}))
    asyncio.run(agent.run('hi'))
    assert provider.kwargs == [{'temperature': 0, 'max_tokens': 10}]


def test_provider_base_default_model_params_is_read_only():
    """베이스 클래스 기본값은 모든 Provider가 공유한다 — 실수로 변경하면 조용히 누출되는 대신 바로 터져야 한다."""
    provider = ScriptedProvider([])
    with pytest.raises(TypeError):
        provider.model_params['temperature'] = 0  # type: ignore[index]
    provider.model_params = {'temperature': 0}  # 인스턴스 속성으로는 자유롭게 설정
    assert provider.model_params == {'temperature': 0}


def test_openai_provider_stores_defaults_and_passes_call_kwargs_through():
    """OpenAIProvider는 합치지 않는다 — 기본값을 들고만 있고, 받은 kwargs를 요청에 그대로 싣는다."""
    provider = OpenAIProvider(model='m', api_key='x', model_params={'temperature': 0.7})
    assert provider.model_params == {'temperature': 0.7}
    captured = {}

    class FakeCompletions:
        async def create(self, **request):
            captured.update(request)
            raise RuntimeError('stop here')  # 응답 변환은 이 테스트의 관심사가 아니다

    provider.client.chat.completions = FakeCompletions()
    try:
        asyncio.run(provider.generate([{'role': 'user', 'content': 'hi'}], temperature=0))
    except RuntimeError:
        pass
    assert captured == {'model': 'm', 'messages': [{'role': 'user', 'content': 'hi'}], 'temperature': 0}
