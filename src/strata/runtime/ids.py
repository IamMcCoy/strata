from __future__ import annotations

import os
import time
import uuid


def new_run_id() -> str:
    """run 하나를 가리키는 유일한 이름. UUIDv7 (RFC 9562).

    앞 48비트가 Unix 밀리초라 **문자열 정렬이 곧 생성 시각순**이다 —
    실행 기록을 DB에 저장할 때 인덱스가 끝에 append되고, created_at 컬럼도 필요 없다.

    코어가 발급한다. 외부 id(앱의 task_id 등)를 받지 않는다 (ADR-0011) —
    코어가 남기는 기록의 유일성을 외부 문자열에 의존시킬 수 없기 때문이다.
    """
    # ponytail: uuid.uuid7()은 Python 3.14 stdlib. requires-python이 3.14로 올라가면
    # 이 함수를 지우고 위임한다. 지금은 3.12/3.13 사용자를 위해 직접 만든다.
    # ponytail: 같은 밀리초 안에서는 순서가 무작위다(RFC의 counter 방식 미구현).
    # 초당 수천 run이 되면 counter를 단다.
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF          # bits 127..80
    value = (ms << 80) | int.from_bytes(os.urandom(10), 'big')
    value &= ~(0xF << 76)
    value |= 0x7 << 76                                      # version = 7
    value &= ~(0x3 << 62)
    value |= 0x2 << 62                                      # variant = RFC 4122
    return str(uuid.UUID(int=value))
