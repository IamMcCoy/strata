"""run_id — UUIDv7 (RFC 9562). 형식·정렬·유일성이 실행 기록의 전제다 (ADR-0011)."""
from __future__ import annotations

import time
import uuid

from strata.runtime.ids import new_run_id


def test_is_a_valid_uuid_v7():
    parsed = uuid.UUID(new_run_id())
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122


def test_string_sort_is_time_order():
    """DB 인덱스 지역성과 로그 정렬이 여기 걸려 있다 — uuid4를 쓰지 않는 이유."""
    ids = []
    for _ in range(5):
        ids.append(new_run_id())
        time.sleep(0.002)
    assert sorted(ids) == ids


def test_timestamp_is_recoverable():
    """created_at 컬럼이 필요 없는 이유 — 시각이 id 안에 있다."""
    before = time.time()
    embedded = uuid.UUID(new_run_id()).int >> 80
    assert before - 1 <= embedded / 1000 <= time.time() + 1


def test_is_unique():
    assert len({new_run_id() for _ in range(10000)}) == 10000


if __name__ == '__main__':
    test_is_a_valid_uuid_v7()
    test_string_sort_is_time_order()
    test_timestamp_is_recoverable()
    test_is_unique()
    print('ids ok')
