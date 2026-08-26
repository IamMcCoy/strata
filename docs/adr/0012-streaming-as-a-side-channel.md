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

Anthropic만 별도인 이유는 메시지 형식이 근본적으로 달라서다: system이 메시지가 아니라
최상위 파라미터고, tool 호출/결과가 role이 아니라 content block이며, tool 결과는
`role='user'`의 `tool_result` 블록으로 들어간다. 그리고 `total_tokens`를 주지 않아
`token_budget` 집계를 위해 Provider가 합을 만든다.

### 재시도

- **코어에 재시도 계층을 두지 않는다.** SDK 설정을 노출만 한다:
  `OpenAIProvider(..., max_retries=5, timeout=30)`.
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
- (−) Gemini는 OpenAI 호환 계층을 거치므로 네이티브 기능(thinking 등)을 못 쓴다.
  필요해지면 그때 네이티브 `GeminiProvider`를 만든다.
- (−) 재시도를 SDK에 맡기므로 Provider별 재시도 동작이 미묘하게 다를 수 있다.
  통일이 필요해지면 그때 코어로 올린다.
