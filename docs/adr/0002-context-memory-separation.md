# 0002. Context와 Memory를 분리한다

- 상태: Accepted
- 날짜: 2026-08-20

## Context

"Agent가 아는 것"은 두 가지 수명을 가진다: 현재 실행 동안만 유효한 상태
(메시지, tool 결과, child 결과)와, 실행이 끝나도 보존해 재사용할 정보
(과거 경험, 사실, 절차). 이를 하나의 개념으로 합치면 재귀 실행에서 특히 문제가 된다 —
child의 임시 상태가 영속 저장소에 섞이거나, 반대로 영속 정보가 실행마다 초기화된다.

## Decision

- **Context** = 현재 실행의 상태. 실행 종료 후 지속을 보장하지 않는다.
- **Memory** = 실행 간 영속 정보. `store / retrieve / delete` 인터페이스로 접근한다.
- 흐름은 단방향으로 고정한다: `Memory → Retrieve → Context → Strategy`,
  실행 중 보존할 가치가 생긴 정보만 명시적으로 `Memory.store`.
- Working Memory는 Context와 역할이 겹치므로 초기에는 별도 타입으로 만들지 않고
  Context가 담당한다. Episodic / Semantic / Procedural은 `MemoryItem`의 타입 필드로
  시작하고 필요 시 분화한다.

## Consequences

- (+) Child Agent에 독립 Context를 주는 것이 자연스럽다 (Memory는 공유 가능, Context는 격리).
- (+) Memory backend(InMemory → Redis/Vector/SQL)를 실행 로직 변경 없이 교체할 수 있다.
- (−) "무엇을 언제 store할 것인가"라는 정책 문제가 남는다. 초기에는 Strategy/사용자의
  명시적 호출로 두고, 자동 축적은 이후 과제로 미룬다.
