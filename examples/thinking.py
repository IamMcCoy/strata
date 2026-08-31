"""사고 모드(thinking/reasoning)가 **실제로 켜졌는지** 확인한다.

    export VLLM_BASE_URL=http://192.168.1.70:8000/v1 VLLM_MODEL=Gemma4-12B-it
    uv run python examples/thinking.py

파라미터를 넘겼다고 켜진 게 아니다 — 모르는 키는 서버가 조용히 무시한다.
증거는 두 가지뿐이고, 벤더마다 어느 쪽을 주는지가 다르다:

    reasoning        사고 과정 텍스트. vLLM/DeepSeek는 원문, Claude도 원문, Gemini는 요약본.
    reasoning_tokens 사고에 쓴 토큰 수. OpenAI 순정은 **텍스트를 절대 안 주므로** 이것만이 증거다.

둘 다 없으면 사고는 꺼져 있거나 서버가 파라미터를 무시한 것이다.

**reasoning_tokens가 0이 아니라고 켜진 게 아니다** — 실측(Gemma4-12B/vLLM): 사고를 꺼도
빈 `<think></think>` 블록 때문에 2가 찍힌다. 켜면 552다. 그래서 이 파일은 같은 모델을
껐다 켰다 두 번 부른다 — 절대값이 아니라 **차이**가 증거다.

켜는 법이 벤더마다 다르다(코어가 해석하지 않는 model_params로 그대로 내려간다):

    vLLM       extra_body={'chat_template_kwargs': {'enable_thinking': True}}
    OpenAI     reasoning_effort='high'                      (o-시리즈/gpt-5)
    Claude     thinking={'type': 'enabled', 'budget_tokens': 2048}   (max_tokens > budget)
    Gemini     thinking_config=ThinkingConfig(include_thoughts=True, thinking_budget=1024)
"""
from __future__ import annotations

import asyncio
import logging
import os

from strata.agent import Agent
from strata.providers import AnthropicProvider
from strata.providers import GeminiProvider
from strata.providers import OpenAIProvider
from strata.providers.base import Provider
from strata.providers.base import ProviderError
from strata.strategies import ReActStrategy
from strata.tools import PythonTool

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

QUESTION = [{'role': 'user', 'content': '17 * 23은? 계산 과정을 거쳐 답만 말해줘.'}]


async def probe(label: str, provider: Provider, **params) -> None:
    """한 번 호출해서 사고의 흔적이 실려 오는지 본다.

    한 벤더가 죽어도(키 만료·크레딧 부족·서버 다운) 나머지는 계속 본다 —
    여러 벤더를 훑는 게 이 파일의 유일한 목적이라 첫 실패에서 멈추면 쓸모가 없다.
    """
    print(f'\n[{label}]')
    try:
        response = await provider.generate(QUESTION, **params)
    except ProviderError as exc:
        # ProviderError = 인프라 오류(ADR-0013). 내 코드 버그가 아니므로 건너뛴다.
        print(f'  => 확인 불가: {exc}')
        return
    reasoning_tokens = response.usage.get('reasoning_tokens')
    print(f'  text            : {(response.text or "")[:80]!r}')
    print(f'  reasoning       : {(response.reasoning or "(없음)")[:80]!r}')
    print(f'  reasoning_tokens: {reasoning_tokens or "(없음)"}')
    if response.reasoning:
        verdict = '켜짐 — 사고 텍스트가 왔다'
    elif reasoning_tokens:
        # 숫자만으로는 단정할 수 없다. 실측: vLLM은 사고를 꺼도 빈 <think></think>의 2토큰을 보고한다.
        verdict = f'토큰만 관측({reasoning_tokens}) — 텍스트를 안 주는 벤더거나 빈 사고 블록이다. off와 비교하라'
    else:
        verdict = '꺼짐 또는 서버가 파라미터를 무시함'
    print(f'  => 사고 모드 {verdict}')


async def through_the_agent(provider: OpenAIProvider) -> None:
    """Provider 단독이 아니라 실제 Agent 경로(전략 + tool + 스트리밍)에서도 확인한다.

    Agent.run은 AgentResult를 주지 사고 과정을 주지 않는다 — 일부러다(불변식 4·5).
    그래서 여기서는 두 가지를 본다:
      1. 결과   result.metadata['reasoning'] — generate 호출 순서대로 쌓인 사고 원문.
      2. 로그   Runtime.generate가 매 호출에 reasoning=<길이>를 DEBUG로 남긴다.
      3. 출력   on_delta에 사고가 섞이지 않는지 — 여기서 모은 것과 최종 답이 같아야 한다.
    """
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')
    for noisy in ('httpx', 'httpcore', 'openai'):
        # SDK의 DEBUG 덤프가 요청 본문까지 다 찍어서 정작 볼 줄이 묻힌다
        logging.getLogger(noisy).setLevel(logging.WARNING)

    streamed: list[str] = []
    agent = Agent(
        provider=provider,
        strategy=ReActStrategy(),
        tools=[PythonTool()],
        instructions='한국어로 답해줘.',
        on_delta=lambda text, execution_id=None: streamed.append(text),
    )
    result = await agent.run('17 * 23을 계산해서 답만 말해줘.')

    print(f'\n  status : {result.status}')
    print(f'  result : {(result.result or "")[:80]!r}')
    print(f'  streamed: {"".join(streamed)[:80]!r}')
    for i, reasoning in enumerate(result.metadata.get('reasoning', [])):
        print(f'  reasoning[{i}]: {reasoning[:70]!r}')
    if 'reasoning' not in result.metadata:
        print('  reasoning: (없음) — 사고가 꺼져 있거나 서버가 파라미터를 무시했다')


async def main() -> None:
    ran = False

    if os.environ.get('VLLM_BASE_URL'):
        ran = True
        thinking = {'extra_body': {'chat_template_kwargs': {'enable_thinking': True}}}
        vllm = OpenAIProvider(
            model=os.environ.get('VLLM_MODEL', 'local'),
            api_key='not-needed', base_url=os.environ['VLLM_BASE_URL'],
        )
        # 같은 서버·같은 모델을 껐다 켰다 비교하는 것이 이 파일의 핵심이다.
        # 한쪽만 보면 "원래 안 주는 모델"과 "꺼져 있음"을 구분할 수 없다.
        for enabled in (False, True):
            await probe(
                f'vLLM enable_thinking={enabled}', vllm,
                extra_body={'chat_template_kwargs': {'enable_thinking': enabled}},
            )
        if os.environ.get('AGENT'):   # 로그가 길어서 기본으로는 안 돈다
            print('\n[vLLM — Agent 경로 (ReAct + tool + 스트리밍)]')
            await through_the_agent(
                OpenAIProvider(
                    model=os.environ.get('VLLM_MODEL', 'local'),
                    api_key='not-needed', base_url=os.environ['VLLM_BASE_URL'],
                    model_params=thinking,
                ),
            )

    if os.environ.get('OPENAI_API_KEY'):
        ran = True
        # 순정 OpenAI는 사고 텍스트를 주지 않는다 — reasoning은 None이고 토큰 수만 올라간다.
        await probe(
            'OpenAI reasoning_effort',
            OpenAIProvider(model=os.environ.get('OPENAI_REASONING_MODEL', 'o4-mini')),
            reasoning_effort='medium',
        )

    if os.environ.get('ANTHROPIC_API_KEY'):
        ran = True
        await probe(
            'Claude extended thinking',
            AnthropicProvider(model=os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5'), max_tokens=4096),
            # budget_tokens < max_tokens이어야 한다.
            # temperature/top_p/top_k는 anthropic SDK 1.0에서 create()에서 사라졌다 —
            # 넘기면 TypeError다. 대신 output_config={'effort': 'low'|...|'max'}를 쓴다.
            thinking={'type': 'enabled', 'budget_tokens': 2048},
        )

    if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
        ran = True
        from google.genai import types
        await probe(
            'Gemini include_thoughts',
            GeminiProvider(model=os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash-lite')),
            # include_thoughts=False면 thought part 자체가 안 온다 — 토큰 수만 남는다.
            thinking_config=types.ThinkingConfig(include_thoughts=True, thinking_budget=1024),
        )

    if not ran:
        print('환경변수가 없다. 하나 이상 설정하고 다시 실행:')
        print('  VLLM_BASE_URL / OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY')


if __name__ == '__main__':
    asyncio.run(main())
