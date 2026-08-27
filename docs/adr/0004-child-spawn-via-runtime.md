# 0004. Child Agent 생성은 runtime.spawn_agent()를 경유한다

- 상태: Accepted
- 날짜: 2026-08-20

## Context

RecursiveStrategy가 child agent를 만드는 방법은 두 가지다:

1. Strategy가 `Agent(...)`를 직접 인스턴스화
2. Runtime의 spawn 기능을 호출

직접 생성하면 Strategy가 Agent 구현·구성 방식에 강하게 결합되고, 더 중요하게는
**Runtime이 child 실행을 볼 수 없다** — depth/children 한도 강제, token budget 집계,
Execution Tree 등록, `agent.spawned` 이벤트가 모두 불가능해진다.

## Decision

Child Agent 생성은 반드시 `runtime.spawn_agent(task, parent_context, strategy=None)`을
경유한다. Runtime은 spawn 시점에:

1. 실행 한도 검사 (max_depth, max_children, token_budget)
2. 독립 Child Context 생성
3. Execution Node 등록 (parent_id 연결)
4. `agent.spawned` 이벤트 발행

을 수행하고, child의 결과 계약(status/result/evidence/metadata)만 반환한다.
`spawn_agent`는 async로 설계해 향후 여러 child의 병렬 실행을 지원할 수 있게 한다.

## Consequences

- (+) 무한 재귀·비용 폭발 방지가 Strategy 구현 품질과 무관하게 보장된다
  (Custom Strategy가 실수해도 Runtime이 막는다).
- (+) 모든 재귀 실행이 관찰 가능(Execution Tree + Events).
- (+) RLM 논문의 한계였던 동기식 재귀를 병렬화할 수 있는 지점이 Runtime 한 곳에 모인다.
- (−) Strategy가 Runtime 없이는 단독 테스트가 어렵다. 테스트용 Fake Runtime을
  제공하는 것으로 해소한다.
