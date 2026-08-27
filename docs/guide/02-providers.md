# 2. Provider

모델을 붙이는 자리. 코어는 어떤 SDK도 import하지 않으므로, 쓰는 것만 extra로 설치한다.

```bash
uv add 'strata[openai]'      # OpenAI, 그리고 OpenAI 호환 엔드포인트 전부
uv add 'strata[anthropic]'   # Claude
uv add 'strata[gemini]'      # Gemini 네이티브
uv add 'strata[all]'
```

## 네 가지 + 호환 계열

```python
from strata import OpenAIProvider, AnthropicProvider, GeminiProvider

OpenAIProvider(model='gpt-4o-mini')                       # OPENAI_API_KEY 환경변수 사용
AnthropicProvider(model='claude-sonnet-5', max_tokens=4096)
GeminiProvider(model='gemini-3.5-flash-lite')
```

**vLLM·Ollama·OpenRouter는 별도 클래스가 아니다.** OpenAI 호환 API이므로 `base_url`만 바꾼
같은 코드다:

```python
OpenAIProvider(model='Gemma4-12B-it', api_key='not-needed',
               base_url='http://192.168.1.70:8000/v1')          # vLLM
OpenAIProvider(model='llama3.1', api_key='not-needed',
               base_url='http://localhost:11434/v1')            # Ollama
OpenAIProvider(model='anthropic/claude-sonnet-4', api_key=OPENROUTER_KEY,
               base_url='https://openrouter.ai/api/v1')         # OpenRouter
```

Claude와 Gemini만 별도 구현인 이유는 성능이 아니라 **메시지 구조가 근본적으로 다르기**
때문이다 — Claude는 system이 최상위 파라미터이고 tool 호출·결과가 content block이며,
Gemini는 system이 config이고 assistant가 `role='model'`이며 tool이 part다.

### vLLM에서 tool을 쓰려면

서버가 `--enable-auto-tool-choice --tool-call-parser <파서>`로 떠 있어야 한다. 없으면 tool을
넘기는 순간 400이다. **코드 문제가 아니라 서버 기동 옵션이다.**

## 공통 파라미터

```python
OpenAIProvider(
    model,                      # 필수
    api_key=None,               # 없으면 OPENAI_API_KEY 환경변수
    base_url=None,              # 호환 엔드포인트
    max_retries=2,              # 429·5xx·연결 오류를 SDK가 지수 백오프로 재시도 (총 3회 시도)
    model_params=None,          # {'temperature': 0.2, ...} 배포 기본값
    **client_kwargs,            # timeout 등 — SDK 생성자로 그대로 간다
)
```

**재시도는 SDK에 맡긴다.** 코어에 재시도 계층을 겹치지 않는 이유는 백오프가 곱해지기 때문이다
(3회 × 3회 = 9회, 대기시간은 그보다 더). 긴 재귀 실행에서 rate limit 한 번으로 전체를 잃고
싶지 않으면 `max_retries`를 올린다. 단 **총 대기시간이 대략 `max_retries × timeout`**이므로
둘을 같이 정한다.

`model_params`의 우선순위는 **Strategy > Provider**다. 배포 기본값을 Provider에 두고,
특정 패턴만 다르게 하고 싶으면 전략에 준다:

```python
OpenAIProvider(model='gpt-4o-mini', model_params={'temperature': 0.7})   # 기본
ReActStrategy(model_params={'temperature': 0})                            # 이 전략만 0
```

코어는 이 dict를 해석하지 않고 SDK로 그대로 넘긴다. 지원 키가 벤더마다 다르기 때문이다
(`top_k`는 Anthropic만, reasoning 모델은 `temperature`를 거부).

## 스트리밍

`Agent`에 `on_delta`를 주면 켜진다. Strategy 코드는 아무것도 바뀌지 않는다.

```python
agent = Agent(
    provider=OpenAIProvider(model='gpt-4o-mini'),
    strategy=ReActStrategy(),
    on_delta=lambda text, execution_id: print(text, end='', flush=True),
)
result = await agent.run(task)      # 반환은 여전히 완결된 AgentResult
```

`execution_id`가 함께 오므로 재귀 실행에서 **어느 agent의 출력인지** 구분할 수 있다.
웹 서버라면 이걸 SSE 큐에 밀어 넣으면 된다:

```python
on_delta=lambda text, execution_id: queue.put_nowait({'id': execution_id, 'text': text})
```

주의: 호환 계층이 `stream_options: {include_usage: true}`를 받지 않으면 **usage가 0으로
샌다.** 그러면 `token_budget`이 조용히 무력화된다. 새 엔드포인트를 붙였으면 한 번 확인하라:

```python
assert agent.runtime.usage['total_tokens'] > 0
```

## 오류

프로바이더의 SDK 예외는 `ProviderError`로 번역되어 **결과 계약**으로 돌아온다:

```python
result = await agent.run(task)
if result.status == 'failed' and result.metadata.get('reason') == 'provider_error':
    print(result.metadata['detail'])     # 'RateLimitError: ...'
    print(result.result)                 # 그래도 지금까지의 답은 살아 있다
```

여기 도달했다는 것은 **SDK 재시도가 이미 소진됐다**는 뜻이다. 즉시 다시 부르지 말고
백오프하거나 다른 프로바이더로 넘어가라.

## 폴백

```python
from strata import FallbackProvider

provider = FallbackProvider([
    OpenAIProvider(model='gpt-4o-mini'),
    AnthropicProvider(model='claude-sonnet-5'),
])
```

앞에서부터 시도하고 `ProviderError`가 나면 다음으로 넘어간다. 마지막까지 실패하면 그때
`ProviderError`가 올라간다.

**주의**: context 초과(`400 context_length_exceeded`)도 `ProviderError`다. 이건 재시도해도
영원히 안 되는 오류라 폴백이 다음 프로바이더에서도 똑같이 실패하며 비용만 쓴다. 입력이 클
가능성이 있으면 폴백에 기대지 말고 [5. 멀티턴](05-conversation.md)의 자르기를 먼저 하라.

## 직접 만들기

```python
from strata import Provider, ModelResponse, ToolCall

class MyProvider(Provider):
    async def generate(self, messages, tools=None, **kwargs):
        # messages: [{'role': 'system'|'user'|'assistant'|'tool', 'content': ..., ...}]
        # tools:    list[Tool] — .name / .description / .input_schema 를 읽어 벤더 형식으로
        return ModelResponse(
            text='...',
            tool_calls=[ToolCall(name='add', arguments={'a': 1, 'b': 2}, id='call_1')],
            usage={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )
```

`usage`를 채우지 않으면 `token_budget`이 동작하지 않는다. 스트리밍을 지원하려면
`on_delta` 키워드를 받아 조각마다 호출하되, 반환은 여전히 완결된 `ModelResponse`여야 한다.
