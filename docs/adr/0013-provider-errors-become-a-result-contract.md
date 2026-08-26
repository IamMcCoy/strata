# 0013. 인프라 오류는 결과 계약으로, 프로그래밍 오류는 그대로 — 번역은 Provider가 한다

- 상태: Accepted
- 날짜: 2026-08-26

## Context

같은 "더 진행할 수 없는" 상황인데 결말이 달랐다.

```text
예산 소진  → status='budget_exceeded', result='2장까지 분석했습니다'   지금까지의 답이 남는다
429       → 예외 폭발, result를 받을 방법이 없다                      통째로 버려진다
```

둘 다 이미 토큰을 지불한 상태다. 30분짜리 재귀가 child 8개를 돌려 5만 토큰을 쓴 뒤
마지막 호출에서 rate limit 하나를 맞으면 그 결과가 전부 사라진다. SDK의 재시도
(ADR-0012)는 일시적 오류를 흡수하지만, **재시도가 소진된 뒤**는 여전히 예외 전파다.

그렇다고 `Agent.run`에서 `except Exception`으로 다 잡으면 안 된다. Strategy의 `TypeError`
같은 프로그래밍 오류까지 `status='failed'`로 조용히 삼켜져 원인을 찾을 수 없게 된다 —
지금 코드가 일부러 다시 던지는 이유다("프로그래밍 오류는 사용자가 봐야 한다").

즉 **인프라 오류와 프로그래밍 오류를 구분해야** 하는데, "429다"를 알려면
`openai.RateLimitError`인지 봐야 하고, 코어가 `openai`를 import하면 `dependencies = []`가 깨진다.

## Decision

- **`ProviderError`(`providers/base.py`)를 둔다.** Provider가 자사 SDK 예외를 이걸로 번역한다.
  벤더 번역이 Provider의 책임인 것은 usage 표준 키·메시지 형식과 같은 이유다 —
  코어는 `openai`가 무엇인지 영원히 몰라도 된다.
- 세 SDK 모두 `APIError` 단일 최상위로 정리돼 있어 **한 줄로 잡는다**
  (`RateLimitError`/`APIConnectionError`/`APITimeoutError`/`AuthenticationError`가 전부 그 아래).
  SDK가 새 예외를 추가해도 자동으로 덮인다.
- `Runtime.run_strategy`가 `BudgetExceeded`/`Cancelled` 옆에서 계약으로 변환한다:
  `AgentResult(status='failed', result=<마지막 assistant 텍스트>, metadata={'reason': 'provider_error', 'detail': ...})`.
  **새 배관이 아니라 기존 배관에 한 줄이다.**
- `execute_tool`도 `ProviderError`를 관찰 문자열로 바꾸지 않고 통과시킨다
  (`Cancelled`와 같은 이유 — `SpawnAgentTool`처럼 Tool 안에서 primitive가 불릴 수 있다).
- 새 status를 만들지 않는다. `failed` + `metadata['reason']`으로 충분하다.
- **폴백은 코어가 아니라 `FallbackProvider`로** 한다 — `Provider` ABC만 구현하므로
  코어 수정이 0줄이고 어떤 Strategy와도 동작한다. 벤더가 바뀌면 답의 품질도 바뀌므로
  사용자가 명시적으로 선택해야 하는 일이다.

### `AuthenticationError`/`BadRequestError`도 포함하는 이유

셋 다 *내 파이썬 코드의 버그가 아니고*, 부분 결과를 살리는 편이 사용자에게 이롭다.
원인은 `metadata['detail']`에 원문으로 남아 보인다.

### 폴백의 스트리밍 함정

이미 조각을 흘린 뒤 폴백하면 **사용자 화면에 텍스트가 두 번 나온다.**
그래서 `FallbackProvider`는 **첫 델타가 나가기 전에 실패한 경우에만** 다음으로 넘어가고,
그 뒤라면 그대로 올린다. 프로그래밍 오류에도 폴백하지 않는다 —
같은 버그를 벤더 수만큼 반복 실행할 뿐이다.

## Consequences

- (+) 인프라 오류에서 이미 지불한 토큰의 결과를 건진다. transcript(ADR-0010)도 함께 돌아와
  대화를 이어갈 수 있다.
- (+) 프로그래밍 오류는 그대로 전파된다 — 디버깅 경험이 나빠지지 않는다.
- (+) 코어는 여전히 어떤 SDK도 import하지 않는다.
- (+) 폴백이 필요한 사람만 `FallbackProvider`를 쓴다. 코어에 벤더 우선순위 정책이 없다.
- (−) `status='failed'`가 두 가지를 뜻하게 된다: child의 일반 실패와 인프라 오류.
  `metadata['reason']`으로만 갈린다. 새 status를 늘리는 것보다 낫다고 판단했다.
- (−) Provider 구현자는 자사 SDK 예외를 번역할 의무를 진다. 안 하면 프로그래밍 오류로
  취급돼 run이 폭발한다 — 각 Provider의 `generate`가 `_call`을 감싸는 형태로 강제한다.
- (−) 재시도 자체는 여전히 strata에 보이지 않는다(ADR-0012). `ProviderError`는 재시도가
  **소진된 뒤**에만 도달한다.
