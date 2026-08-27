# 0003. Strategy를 독립적인 실행 abstraction으로 만든다

- 상태: Accepted
- 날짜: 2026-08-20

## Context

Agent의 실행 패턴(ReAct, Recursive, Reflection, …)을 표현하는 가장 단순한 방법은
Agent 클래스 안의 enum + if/else 분기이지만, 그 방식은:

- 새 패턴 추가 = 프레임워크 코드 수정 (사용자 확장 불가)
- 패턴 조합(Recursive 안의 ReAct 안의 Reflection) 표현 불가
- Agent가 모든 패턴의 실행 로직을 떠안아 비대해짐

Strata의 목표는 "다양한 Agentic Pattern을 동일한 인터페이스에서 구현·조합"이므로,
패턴 자체가 확장 포인트여야 한다.

## Decision

Strategy를 `execute(context, runtime) -> AgentResult` 단일 메서드의 독립 abstraction으로
만든다. Agent는 조합(Provider/Strategy/Tools/Memory)만 담당하고 실행 로직을 갖지 않는다.
사용자는 `Strategy`를 상속한 Custom Strategy를 만들어 Runtime의 공통 capability
(provider, tools, memory, spawn_agent, events)를 그대로 사용할 수 있다.

## Consequences

- (+) `strategy=` 인자 교체만으로 실행 패턴이 바뀐다. 프레임워크의 핵심 확장 포인트 확보.
- (+) Strategy Composition(Phase 8)이 가능해진다 — spawn 시 child의 strategy를 지정.
- (+) Provider ≠ Strategy 분리와 결합해, 동일 패턴을 어떤 모델 위에서도 실행할 수 있다.
- (−) 단순한 단발 호출 use case에도 Strategy 계층이 끼어든다. 가장 단순한
  "한 번 물어보고 끝" 패턴도 최소 Strategy 하나로 표현해야 한다.
