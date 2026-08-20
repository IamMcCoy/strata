# 0008. LLM 호출을 포함한 세 primitive는 모두 Runtime을 경유한다 (runtime.generate)

- 상태: Accepted
- 날짜: 2026-08-21

## Context

설계는 "한도의 강제는 Strategy가 아니라 Runtime의 책임"(runtime.md)이라 했지만,
Strategy가 `runtime.provider.generate()`를 직접 호출하는 한 Runtime은 LLM 호출을
볼 수 없었다 — `max_iterations`는 Strategy가 스스로 지키는 약속이었고,
`token_budget`·`timeout`·`provider.*` 이벤트·usage 집계는 걸 지점이 없었다.
세 primitive(`generate` / `execute_tool` / `spawn_agent`) 중 `generate`만 Runtime 메서드가
아닌 비대칭이 원인이다.

## Decision

- `Runtime.generate(context, tools=None, instructions=None, **kwargs)`가 Provider 호출의
  유일한 경로다. system 메시지 조립, 노드당 `max_iterations` 집계, run 전체 `token_budget`
  검사, usage 누적(향후 이벤트 발행)이 여기서 일어난다. Strategy는 `runtime.provider`를 직접 쓰지 않는다.
- 한도 초과는 내부 신호 `BudgetExceeded`로 Strategy에 올라가고, `Runtime.run_strategy`
  (Agent.run / spawn_agent 공통 경로)가 **`AgentResult(status='budget_exceeded',
  result=<지금까지의 마지막 assistant 텍스트>)`** 로 변환한다. Strategy가 잡지 않아도 된다 —
  Custom Strategy가 한도를 몰라도 Runtime이 막는다.
- `timeout`은 `Agent.run`이 run 전체에 `asyncio.timeout`으로 적용하고 같은 계약으로 변환한다.

## Consequences

- (+) runtime.md의 불변식이 실제로 성립한다. Phase 5(Runtime Control)가 이 결정으로 대부분 완료된다.
- (+) Phase 6 이벤트·비용 추적을 붙일 지점이 한 곳(generate/execute_tool/spawn_agent)으로 모인다.
- (−) Strategy 단독 테스트에 Runtime(또는 Fake)이 항상 필요하다 — ADR-0004와 같은 비용.
- (−) `execution_id`가 없는 임시 Context로 generate하면 iteration 집계를 받지 않는다(token_budget만 적용).
  Self-Consistency 같은 다중 샘플 패턴이 이 경로를 쓴다 — 의도된 동작이며 문서화한다.
