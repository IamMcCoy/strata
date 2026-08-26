# 0011. run_id는 코어가 발급하고 외부 id를 받지 않는다 — 취소는 하드/협조적 두 종류

- 상태: Accepted
- 날짜: 2026-08-26

## Context

**식별자.** `ExecutionNode.id`(`exec_0`, `exec_1`…)는 `ExecutionManager` 안에서만 유일하고,
`ExecutionManager`는 run당 하나다(ADR-0006). 그래서 **모든 run의 root가 `exec_0`이다** —
같은 프로세스의 연속된 두 run도, 동시에 도는 워커 둘도 마찬가지다. 실행 기록을 저장하거나
로그를 남기는 순간 서로 뒤섞여 복원할 수 없다.

앱은 대개 자기 식별자를 이미 갖고 있다(큐 job id, HTTP request id). 그걸 코어가 받아쓰면
correlation은 쉬워지지만, **제어(취소)와 기록의 권위가 외부 문자열에 넘어간다** —
두 워커가 같은 값을 넘기면 기록이 덮이고, 취소가 엉뚱한 run을 지목한다.
게다가 앱의 식별자는 **일감(work item)**이고 코어가 남기는 것은 **시도(attempt)**라,
재시도가 일어나면 1:N이 된다. 하나로 합칠 수 없다.

**취소.** `asyncio.Task.cancel()`은 이미 코어를 깨끗이 통과한다(모든 예외 핸들러가
`except Exception`이라 `CancelledError`가 삼켜지지 않는다). 하지만 그것은 즉시 끊는
방식이라 **이미 쓴 토큰이 통째로 버려진다.** 3만 토큰을 쓴 재귀 실행에서는 대개
"즉시 죽여라"가 아니라 "지금까지 한 걸로 마무리해라"가 필요하다.

## Decision

### 식별자

- `Runtime`이 생성될 때 `run_id`를 발급한다. 형식은 **UUIDv7**(RFC 9562, `runtime/ids.py`).
  앞 48비트가 Unix ms라 문자열 정렬이 곧 시각순이다 — 실행 기록의 DB 인덱스가 끝에 append되고
  `created_at` 컬럼이 필요 없다.
- child는 parent의 Runtime을 공유하므로(ADR-0006) `run_id`도 공유한다 — **재귀 전체가 하나의 run**이다.
- **`Agent.run`은 `run_id` 인자를 받지 않는다.** 외부 id는 코어의 관심사가 아니다.
  `result.metadata['run_id']`로 내보내기만 하고, 앱이 자기 `task_id` 옆에 적어둔다.
- 두 층으로 읽는다: `run_id`(전역 유일, 프로세스를 넘음) + `execution_id`(그 run 안의 노드).

### 취소

| | 하드 | 협조적 |
|---|---|---|
| 호출 | `asyncio.Task.cancel()` | `runtime.cancel(reason)` |
| 시점 | 즉시, `await` 지점 | 다음 primitive 경계 |
| 부분 결과 | 없음 (예외 전파) | `AgentResult(status='cancelled', result=<마지막 답>)` |
| tree 기록 | `cancelled` | `cancelled` |

- 협조적 취소는 **`BudgetExceeded`와 같은 배관**을 쓴다: `Runtime._check_stop()`이
  `generate`/`spawn_agent`에서 플래그를 보고 `Cancelled` 신호를 올리면
  `run_strategy`가 계약으로 변환한다. Strategy는 취소를 몰라도 되고, Custom Strategy에도 적용된다.
- 검사는 **Provider 호출 앞**에 있다 — 취소 후 LLM 비용이 발생하지 않는다.
- `spawn_agent`에서 취소는 결과 계약이 아니라 신호로 올린다. depth/children 초과는
  "이 가지만 못 간다"지만 취소는 "run 전체를 멈춰라"이기 때문이다.
- `AgentResult.status`에 `cancelled`를 추가한다 (기존: `completed | failed | budget_exceeded`).
  하드 취소를 `failed`로 두지 않는 이유는 **사용자 취소와 프로그래밍 오류가 다른 사건**이어서다.

## Consequences

- (+) 실행 기록·로그가 프로세스와 run을 넘어 복원 가능해진다. Phase 6의 전제가 갖춰진다.
- (+) 협조적 취소가 이미 쓴 토큰을 살린다. 새 개념 없이 기존 한도 배관을 재사용한다.
- (+) 코어에 취소 브로커를 두지 않는다. 프로세스 간 취소는 앱이 채널을 구독해
  자기 `Runtime`을 찾아 `cancel()`을 부른다 — 큐를 코어에 두지 않은 것과 같은 이유다.
- (−) 앱이 `task_id ↔ run_id`를 잇는 한 필드를 저장해야 한다. 대신 매핑 저장소는 필요 없다
  (`examples/worker.py`가 결과 payload에 한 줄로 넣는다).
- (−) 협조적 취소는 실행 중인 tool을 기다린다 — 취소가 최대 tool 하나만큼 늦는다.
  더 빨라야 하면 `execute_tool`에도 검사를 단다.
- (−) 같은 밀리초 안에서 생성된 `run_id`들의 순서는 무작위다(RFC의 counter 방식 미구현).
  초당 수천 run이 되면 counter를 단다.
- (−) `uuid.uuid7()`은 Python 3.14 stdlib이지만 `requires-python = ">=3.12"`를 유지하기 위해
  직접 구현한다(10줄). 3.12/3.13 사용자를 자르지 않는 편이 낫다는 판단이다.
