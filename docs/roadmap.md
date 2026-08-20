# Roadmap — 구현 우선순위

각 Phase는 이전 Phase 위에 쌓인다. **완료 기준**을 만족하기 전에는 다음 Phase로 넘어가지 않는다.

## Phase 1 — Core Abstraction ✅

Agent, Provider, Tool, Memory, Strategy, Context, Runtime 인터페이스 확립.
**구현보다 abstraction 설계를 우선한다.**

- 완료 기준: `src/strata/` 에 모든 base 클래스가 존재하고, import 및 서브클래싱이
  가능하며, 인터페이스가 [design 문서](design/abstractions.md)와 일치한다.

## Phase 2 — ReAct ✅

최소 Tool Calling Loop.

```text
Agent → ReActStrategy → Provider → Tool → Observation → Loop
```

- 완료 기준: 실제 Provider 1개(또는 fake provider) + Tool 1개로
  `examples/react.py` 가 end-to-end로 동작한다.

## Phase 3 — Recursive / RLM (핵심 Phase)

```text
RecursiveStrategy → runtime.spawn_agent() → Child Context → Child Agent
    → Result(계약) → Parent Context
```

동시에 Execution Tree, `max_depth`, `max_children` 구현.

- 완료 기준: `examples/recursive.py` 에서 depth ≥ 2 의 재귀 실행이 동작하고,
  Execution Tree에 전체 tree가 기록되며, `max_depth` 초과 시
  `budget_exceeded` 로 안전하게 종료된다.

## Phase 4 — Memory

`InMemory` 구현 → 이후 Redis / Vector DB / SQL / Custom 을 연결할 수 있도록
인터페이스 유지. Memory Retrieve / Store lifecycle을 Runtime과 연결.

- 완료 기준: 실행 A에서 store한 정보가 실행 B의 Context에 retrieve되어 주입된다.

## Phase 5 — Runtime Control

`max_depth`, `max_iterations`, `max_children`, `token_budget`, `timeout` 전체 지원.

- 완료 기준: 각 한도를 위반하는 시나리오 테스트가 존재하고, 모두 예외 폭발이 아닌
  `budget_exceeded` 결과 반환으로 종료된다.

## Phase 6 — Execution & Events

Execution Tree 완성 + Event 시스템 (Trace, Logging, Token Usage, Cost).

- 완료 기준: [runtime.md](design/runtime.md#event-system)의 이벤트 전체가 발행되고,
  구독자 하나로 실행 전체의 토큰 사용량을 집계할 수 있다.

## Phase 7 — Reflection

```text
Generate → Critique → Revision → Critique → Final
```

- 완료 기준: `examples/reflection.py` 동작.

## Phase 8 — Strategy Composition

```text
Recursive
 └── ReAct
      └── Reflection
```

- 완료 기준: `spawn_agent(strategy=...)` 로 child의 전략을 지정해 위 조합이 동작한다.

## Phase 9 — Plugin Architecture

Provider / Tool / Memory / Strategy를 외부 Package 형태로 추가.

- 완료 기준: 저장소 밖의 패키지에서 `register_*` 로 등록한 구성요소가
  코어 수정 없이 동작한다.
