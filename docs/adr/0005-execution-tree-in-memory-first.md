# 0005. Execution Tree는 In-Memory로 시작한다

- 상태: Accepted
- 날짜: 2026-08-20

## Context

모든 Agent 실행(특히 Recursive의 tree 구조)을 추적해야 하지만, 초기부터 DB나
외부 Trace Backend(OpenTelemetry 등)를 붙이면 Phase 3(Recursive 구현)의 진행이
인프라 작업에 막힌다. 반면 추적을 아예 생략하면 재귀 디버깅이 불가능하다.

## Decision

- Execution Tree(`ExecutionNode`: id, parent_id, task, depth, status, result, children)는
  **In-Memory 구현으로 시작**한다.
- 단, Strategy·Runtime 코드가 In-Memory 구현체가 아닌 **execution manager
  abstraction에만 의존**하도록 하여, 이후 DB / Trace Backend로 교체 가능하게 유지한다.
- 외부 시스템 연동(logging, tracing, cost 집계)은 Execution Tree 직접 접근이 아니라
  **Event 구독**으로 구현한다 — Tree는 상태, Event는 스트림.

## Consequences

- (+) Phase 3에서 외부 의존성 없이 재귀 실행을 즉시 관찰·디버깅할 수 있다.
- (+) Event 기반 확장 덕분에 backend 교체가 핵심 실행 경로에 영향을 주지 않는다.
- (−) 프로세스 종료 시 실행 기록이 사라진다. 영속 기록이 필요해지는 시점
  (Phase 6 이후)에 backend 구현을 추가한다.
