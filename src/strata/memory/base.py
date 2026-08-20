from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field


@dataclass
class MemoryItem:
    content: str
    # ponytail: 타입은 필드로 시작, 별도 클래스 분화는 필요해질 때 (ADR-0002)
    type: str = 'semantic'  # episodic | semantic | procedural
    id: str | None = None
    metadata: dict = field(default_factory=dict)


class Memory(ABC):
    """실행 간 영속 정보. Context(현재 실행 상태)와 분리된다 — ADR-0002."""

    @abstractmethod
    async def store(self, item: MemoryItem) -> None: ...

    @abstractmethod
    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]: ...

    @abstractmethod
    async def delete(self, memory_id: str) -> None: ...
