# 0006. Runtime은 run당 하나이며 Agent.run이 유일한 진입점이다

- 상태: Accepted
- 날짜: 2026-08-20

## Context

Runtime은 token budget과 Execution Tree라는 **run 전체(root + 모든 child)에 걸친
전역 상태**를 담는다. Agent마다 Runtime을 따로 만들면 재귀 실행에서 예산 집계와
tree가 조각나 실행 제어가 무너진다. 또한 초기 스케치에는 `Agent.run(task)`과
`Runtime.run_agent(agent, task)` 두 진입점이 공존해 어느 쪽이 정식인지 모호했다.

## Decision

- **Runtime 인스턴스는 run당 하나다.** root Agent가 runtime 미지정 시 생성하고,
  child agent는 `runtime.spawn_agent()`가 같은 인스턴스를 공유시킨다.
- **진입점은 `Agent.run(task)` 하나로 통일한다.** `Runtime.run_agent`는 제거 —
  child 실행은 `spawn_agent` 내부의 책임이다.
- spawn 시 미지정 인자(provider, tools, memory, config)는 parent 것을 상속하고,
  `strategy`와 `provider`는 오버라이드할 수 있다 (RLM의 "말단 노드는 가벼운 모델" 전략 지원).

## Consequences

- (+) 예산·Execution Tree가 run 전체에서 일관된다. 한도 강제가 한 곳에서 이루어진다.
- (+) 공개 API가 `Agent.run` 하나로 단순해진다.
- (−) 하나의 Runtime 인스턴스로 여러 run을 연속 실행하면 전역 상태가 섞인다.
  run 시작 시 상태 초기화 규칙이 필요하다 — Phase 5(Runtime Control)에서 구체화한다.
