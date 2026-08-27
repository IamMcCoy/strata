# 0010. 대화 이력은 코어가 소유하지 않는다 — `Agent.run(task, history=...)`로 주고받는다

- 상태: Accepted
- 날짜: 2026-08-26

## Context

`Agent.run`은 매번 `messages=[{'role':'user','content':task}]`로 새 Context를 만든다.
멀티턴 대화(챗봇)에서는 턴 1의 대화가 턴 2에 남지 않는다.

이를 Memory로 해결하려는 유혹이 있으나 잘못된 도구다. `Memory.retrieve`는 키워드 겹침
점수이고 **순서 개념이 없다** — 대화를 `MemoryItem`으로 쌓으면 "3번째 턴에서 뭐라고 했는지"를
복원할 방법이 없다. 대화는 순서가 의미의 일부다. 게다가 매 턴이 저장되면 `rank()`의 분모가
폭발해 진짜 기억("사용자는 uv를 쓴다")이 "네 알겠습니다" 수백 개에 묻힌다. 자동 store를 두지
않기로 한 ADR-0002의 판단이 정확히 이것을 막고 있다.

남은 선택지는 두 가지였다.

1. **`Session` 객체를 코어가 소유** — `session.send(task)`가 내부에 messages를 누적한다.
2. **호출자가 소유** — `run(task, history=[...])`로 넣고 결과로 돌려받는다.

## Decision

수명이 다른 **세 가지**를 명시적으로 가른다.

| | 무엇 | 수명 | 어디에 |
|---|---|---|---|
| Context | 한 `run` 안의 messages (tool 왕복 포함) | run 하나 | `Context.messages` |
| Conversation | run **사이**의 대화 연속 = 멀티턴 | 세션 | **앱의 저장소** |
| Memory | 실행 간 영속되는 *사실* | 영구 | `Memory` 구현체 |

- `Agent.run(task, context=None, history=None)` — `history`는 이전 턴들의 messages이며
  이번 턴의 user 메시지 앞에 그대로 붙는다.
- 반환값의 `metadata['messages']`에 이번 run의 전체 transcript를 담는다. 앱이 저장했다가
  다음 턴에 그대로 `history`로 넘긴다. 한도 초과(`budget_exceeded`)로 잘려도 담긴다 —
  잘린 대화도 이어갈 수 있어야 한다.
- transcript는 **`Agent.run`에서만** 붙인다. `runtime.spawn_agent`가 만드는 child의
  `AgentResult`에는 실리지 않는다 (불변식 4 — 재귀에서 context 폭발 방지).
- 코어는 대화를 저장하지 않는다. `Session` 객체를 두지 않는다.
- **`Context.messages`는 순수 JSON 데이터다.** 앱이 DB·큐·Redis에 저장하는 대상이므로
  파이썬 객체가 섞이면 계약 자체가 성립하지 않는다. Strategy는 `tool_calls`를
  `ToolCall` 객체가 아니라 dict로 넣고, Provider가 dict를 읽어 자사 형식으로 변환한다.
  `ModelResponse.tool_calls`는 객체로 남는다 — 그건 Provider↔Strategy 계약이고 영속되지 않는다.

## Consequences

- (+) `Agent.run`이 **무상태로 남는다.** 멀티 워커 배포에서 그대로 동작한다 —
  `Session` 객체를 두면 "그 객체가 어느 워커에 사는가" 문제가 되살아난다
  (`InMemory`가 프로세스 경계를 못 넘는 것과 같은 문제다).
- (+) 채팅 앱은 이미 대화를 자기 DB에 저장한다(UI 렌더링용). 코어가 또 저장하면
  이중 저장과 동기화 버그가 생긴다.
- (+) 잘라내기 정책(최근 N턴, 토큰 기준 등)이 앱의 몫으로 남는다. 코어가 정할 수 없는
  문제이며, 앱마다 답이 다르다.
- (+) history와 Memory가 층을 이룬다: 최근 턴은 원문으로 `history`에, 잘라내기 전에
  모델이 `remember`로 남긴 것은 사실로 `Memory`에.
- (−) 호출자가 매 턴 두 줄(읽기/쓰기)을 써야 한다. 편의를 위한 `Session` helper는
  필요해지면 코어 밖에서 이 API 위에 얹는다.
- (−) messages에 파이썬 객체를 넣고 싶은 유혹이 생길 때마다 이 계약이 깨진다.
  `tests/test_conversation.py::test_transcript_is_pure_json`이 회귀를 막는다.
- (−) `AgentResult.metadata['messages']`는 root run에서만 채워진다는 비대칭이 생긴다.
  대안(전용 필드)은 child 계약에까지 구멍을 내므로 비대칭을 택했다.
