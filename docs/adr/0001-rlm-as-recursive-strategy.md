# 0001. RLM은 Tool이 아니라 Recursive Strategy로 구현한다

- 상태: Superseded by [0007](0007-spawn-trigger-is-a-tool.md) — "RLM은 Strategy"라는 결론은 유지되나, "Tool vs Strategy" 이분법은 정정됨(트리거는 Tool, 메커니즘은 Runtime)
- 날짜: 2026-08-20

## Context

RLM의 핵심인 `llm_query(sub_context, sub_instruction)` 재귀 호출을 구현하는 방법은
두 가지가 있다:

1. **Tool로 구현** — `LLMQueryTool` 같은 도구를 만들어 어떤 Strategy에서든 호출
2. **Strategy로 구현** — 재귀 실행을 하나의 실행 패턴(RecursiveStrategy)으로 정의

Tool로 구현하면 재귀 호출이 Runtime의 통제 밖에서 일어난다. 재귀 깊이, child 수,
토큰 예산, Execution Tree 추적이 모두 Tool 내부 구현에 숨어버리고, Tool은
"외부 세계와의 상호작용"이라는 책임 정의에서도 벗어난다.

## Decision

RLM은 Agent가 새로운 Agent Execution을 생성하는 **RecursiveStrategy**로 구현한다.
재귀 호출은 `runtime.spawn_agent()`를 통해 이루어지고, child는 독립 Context와
Execution Node를 가지며, 결과 계약(status/result/evidence/metadata)만 parent에 반환한다.

## Consequences

- (+) 재귀 깊이·child 수·예산이 Runtime의 실행 제어(RuntimeConfig)에 자연스럽게 통합된다.
- (+) 모든 child 실행이 Execution Tree에 기록되어 관찰 가능하다.
- (+) RLM이 특수 케이스가 아니라 여러 Strategy 중 하나가 되어, ReAct·Reflection과
  같은 기반 위에서 조합할 수 있다 (예: child가 ReAct로 동작).
- (−) 단순 "하위 LLM 한 번 호출"에도 Agent spawn 비용(Context 생성, Node 등록)이 든다.
  가벼운 단발 호출이 필요하면 Strategy가 `runtime.generate()`를 직접 쓰면 된다
  (원문은 `runtime.provider.generate()` — ADR-0008로 대체).
