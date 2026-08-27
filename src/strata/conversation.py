from __future__ import annotations

from collections.abc import Sequence


def trim_history(messages: Sequence[dict], keep_turns: int) -> list[dict]:
    """멀티턴 history에서 최근 `keep_turns`개의 턴만 남긴다. 원본은 건드리지 않는다.

    코어는 대화를 소유하지 않고 자동으로 자르지도 않는다 (ADR-0010) — 자르는 **정책**은
    앱의 몫이다. 이 함수는 정책이 아니라 **안전한 자르는 지점**을 준다:

        history = trim_history(db.load(session_id), keep_turns=10)
        result = await agent.run(task, history=history)

    순진한 `messages[-20:]`이 왜 위험한가: tool 왕복은 쌍이다.

        {'role': 'assistant', 'tool_calls': [{'id': 'call_1', ...}]}   # ← 이걸 자르고
        {'role': 'tool', 'tool_call_id': 'call_1', ...}                # ← 이것만 남기면 400

    프로바이더는 `tool_call_id`가 가리키는 assistant 메시지가 없으면 요청을 거부한다.
    반대(호출만 남고 결과가 없음)도 마찬가지다.

    그래서 **턴 경계에서만 자른다.** 턴은 `role='user'` 메시지에서 시작하고, 그 턴의
    tool 왕복은 다음 user 메시지 전까지 전부 따라온다 — 경계가 곧 안전 지점이다.
    `keep_turns`를 메시지 수가 아니라 턴 수로 받는 이유이기도 하다: tool을 쓰는 에이전트는
    한 턴이 메시지 열 개가 되기도 해서, 메시지 수는 사용자가 예측할 수 없다.

    남는 것: 토큰 수는 세지 않는다. 모델별 토크나이저가 필요해 런타임 의존성 0이 깨진다.
    턴 하나가 컨텍스트를 넘길 만큼 크면 이 함수로는 못 막는다 — 그때는 요약(정책 C)이나
    사실만 Memory로 옮기는 쪽(정책 D)이다. [설계 문서](../../docs/design/abstractions.md)의
    "대화가 길어지면" 절 참조.
    """
    if keep_turns <= 0:
        return []
    starts = [index for index, message in enumerate(messages) if message.get('role') == 'user']
    if len(starts) <= keep_turns:
        return list(messages)
    return list(messages[starts[-keep_turns]:])
