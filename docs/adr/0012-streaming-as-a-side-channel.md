# 0012. 스트리밍은 콜백(부수 채널)이지 반환 계약이 아니다 — 재시도는 SDK에 맡긴다

- 상태: Accepted
- 날짜: 2026-08-26

## Context

사용자 대면 agent는 토큰 스트리밍이 사실상 필수다. 30초짜리 ReAct 루프에서 화면이
멈춰 있으면 제품이 되지 않는다. 문제는 스트리밍을 **어디에 넣느냐**다.

가장 자연스러워 보이는 방법은 `Agent.stream(task)`가 async generator를 반환하는 것이다.
하지만 그러면 세 가지가 깨진다:

1. **두 번째 진입점**이 생긴다 — ADR-0006이 정한 "진입점은 `Agent.run` 하나"가 무너진다.
2. **모든 Strategy가 스트리밍 변종**을 가져야 한다. ReAct/Recursive/RLM에 더해
   앞으로 만들 Custom Strategy까지 전부.
3. `Runtime.generate`의 **한도·usage·로깅이 두 경로로 갈라진다** — ADR-0008이
   한 곳에 모아둔 것이 다시 흩어진다.

재시도도 같은 자리의 문제다. 429·5xx·연결 오류로 30분짜리 재귀 실행이 통째로 죽으면
쓸 수 없다. 다만 `openai`/`anthropic` SDK는 **이미** 지수 백오프 재시도를 내장하고 있다
(`max_retries`, 기본 2).

## Decision

### 스트리밍

- `Provider.generate(messages, tools=None, on_delta=None, **kwargs) -> ModelResponse`.
  **반환은 스트리밍 여부와 무관하게 완결된 `ModelResponse`다.** `on_delta`는 텍스트 조각이
  도착하는 대로 호출되는 부수 채널일 뿐이다.
- 따라서 **Strategy 코드는 한 줄도 바뀌지 않는다.** 한도·usage 집계도 한 경로로 유지된다.
- `on_delta`는 **동기 콜백**이다. `await`하면 실행이 소비자 속도에 묶인다 —
  앱은 큐에 밀어넣고 자기 태스크에서 소비한다(로깅 구독자와 같은 원칙).
- **`execution_id`는 Runtime이 붙인다.** Provider가 보는 시그니처는 `on_delta(text)`,
  앱이 보는 것은 `on_delta(text, execution_id)`다. Provider는 실행 트리를 몰라야 하고,
  재귀에서 여러 child의 토큰이 섞일 때 누가 말하는지는 코어만 안다.
- 구독자 예외는 삼킨다 — 관찰이 실행을 죽이지 않는다.
- `on_delta`가 없으면 Provider에 **인자 자체를 넘기지 않는다.** 스트리밍을 모르는
  Provider 구현도 그대로 동작한다.

### Provider 커버리지

**넷 중 셋은 같은 코드다.** OpenAI-compatible 엔드포인트는 `base_url`만 바꾸면 된다:

| | 방법 |
|---|---|
| vLLM / Ollama | `OpenAIProvider(base_url='http://localhost:8000/v1')` |
| OpenRouter | `OpenAIProvider(base_url='https://openrouter.ai/api/v1')` |
| Gemini | `OpenAIProvider(base_url='https://generativelanguage.googleapis.com/v1beta/openai/')` |
| **Claude** | `AnthropicProvider` — **별도 구현** |
| **Gemini** | `GeminiProvider` — **별도 구현**(네이티브 SDK). 호환 경로도 남긴다 |

Gemini에 네이티브 구현을 두되 `client.aio.models.generate_content(_stream)` 위에 올린다.
`client.interactions`(next-gen API)를 쓰지 않는 이유는 그것이 `agents`/`environments`/
`triggers`/`webhooks`와 함께 있는 **구글의 agent 실행 API**이기 때문이다 — strata와 같은 층의
추상화라 Provider로 감싸면 Runtime의 한도·usage·재귀 제어가 구글 쪽 상태와 이중으로 겹친다.
Provider가 필요로 하는 것은 무상태 완성 호출이다.

Anthropic이 별도인 이유는 메시지 형식이 근본적으로 달라서다: system이 메시지가 아니라
최상위 파라미터고, tool 호출/결과가 role이 아니라 content block이며, tool 결과는
`role='user'`의 `tool_result` 블록으로 들어간다. 그리고 `total_tokens`를 주지 않아
`token_budget` 집계를 위해 Provider가 합을 만든다.

### 재시도

- **코어에 재시도 계층을 두지 않는다.** SDK 설정을 **명시 인자**로 노출한다:
  `Provider(..., max_retries=2)` — 두 Provider가 같은 이름·같은 기본값(SDK와 동일한 2)을 쓴다.
  `**client_kwargs`에 묻어 보내지 않는 이유는 발견 가능성이다: 시그니처에 없으면 아무도 안 쓴다.
- 코어에서 또 재시도하면 SDK 재시도 위에 겹쳐 **백오프가 곱해지고** 실패 하나가
  최대 n×m번 재시도된다. 실제로 부족하다고 **측정되면** 그때 `Runtime.generate`에 단다.

## Consequences

- (+) ADR-0006(단일 진입점)과 ADR-0008(단일 primitive 경로)이 그대로 유지된다.
  스트리밍을 넣으면서 Strategy 세 개와 Runtime의 한도 로직을 건드리지 않았다.
- (+) Provider 하나 추가로 Claude·Gemini·OpenRouter·vLLM이 모두 커버된다.
- (+) 재귀 스트리밍이 `execution_id`로 갈린다 — 어느 child가 말하는지 앱이 안다.
- (−) 콜백 방식은 backpressure가 없다. 소비자가 느리면 앱의 큐가 자란다.
  토큰 크기에서는 문제되지 않으며, 필요하면 앱이 bounded queue를 쓴다.
- (−) `on_delta`로는 tool_call 조각을 볼 수 없다(텍스트만). 도구 호출 진행 상황까지
  보여줘야 하면 그때 확장한다 — 지금은 텍스트가 실사용의 전부다.
- (−) `google-genai`는 무겁다 — 설치에 25개 패키지(cryptography, google-auth 등)가 딸려온다.
  optional extra라 코어의 `dependencies = []`는 그대로지만 쓰는 쪽은 알아야 한다.
- (−) Gemini의 `max_retries`는 SDK가 **총 시도 횟수**를 받으므로 `+1` 변환이 들어간다.
  세 Provider가 같은 인자 이름·같은 의미를 갖게 하기 위한 비용이다.
- (−) 재시도를 SDK에 맡기므로 Provider별 동작이 미묘하게 다를 수 있고, **재시도가 strata에
  보이지 않는다** — 로그에도 usage에도 안 잡혀서 "이 run이 왜 40초 걸렸나"의 답이
  재시도 3회였어도 알 수 없다.
- (−) **재시도를 다 쓰면 예외가 root까지 올라가 run이 죽는다.** 30분짜리 재귀가 마지막
  호출의 rate limit으로 통째로 날아가는 시나리오는 그대로다 — 협조적 취소처럼 부분 결과를
  살리는 경로가 없다. 필요해지면 Provider 오류를 `status='failed'` 계약으로 변환한다
  (같은 배관, ~10줄).
- (−) **`AnthropicProvider`와 Gemini/OpenRouter/vLLM 경로는 실제 API로 검증되지 않았다.**
  메시지 변환은 단위 테스트로 고정했지만 스트리밍 경로와 tool 왕복은 미확인이다.
  특히 OpenAI 호환 계층이 `stream_options: {include_usage: true}`를 받지 않으면 usage가
  0으로 새어 `token_budget`이 무력화된다. 키가 확보되면 `examples/providers.py`로 확인한다.
  (이 프로젝트에서 실제 호출로만 드러난 선례가 이미 둘 있다: 스트림 미close 커넥션 누수,
  redis.asyncio의 이벤트 루프 바인딩.)
