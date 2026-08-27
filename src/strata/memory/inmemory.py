from __future__ import annotations

from uuid import uuid4

from strata.memory.base import Memory
from strata.memory.base import MemoryItem
from strata.memory.base import rank


class InMemory(Memory):
    """프로세스 안 dict 저장소. Phase 4의 최초 Memory 구현 (ADR-0002).

    같은 인스턴스를 여러 Agent.run에 넘기면 그 사이에 정보가 남는다 —
    "실행 간 영속"의 최소 형태다. 프로세스가 죽으면 사라진다.
    """

    # ponytail: 프로세스 로컬 — 멀티 워커(프로세스)에서는 워커마다 기억이 갈라진다.
    # 영속·공유가 필요해지면 같은 인터페이스의 SQLiteMemory / RedisMemory로 갈아끼운다.
    def __init__(self) -> None:
        self.items: dict[str, MemoryItem] = {}

    async def store(self, item: MemoryItem) -> None:
        item.id = item.id or uuid4().hex[:8]
        self.items[item.id] = item

    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        # list()로 스냅샷 — 순회 중 다른 스레드가 store하면 dict가 크기를 바꿔 터진다.
        # 같은 이벤트 루프 안에서는 store/retrieve에 await가 없어 원자적이다 (여기에 await를 추가하지 말 것).
        return rank(list(self.items.values()), query, limit)

    async def delete(self, memory_id: str) -> None:
        self.items.pop(memory_id, None)
