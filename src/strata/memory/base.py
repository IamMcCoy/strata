from __future__ import annotations

import re
from abc import ABC
from abc import abstractmethod
from collections.abc import Iterable
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


_WORD = re.compile(r'\w+', re.UNICODE)


def _tokens(text: str) -> set[str]:
    """1글자 토큰은 버린다 — 어디에나 들어맞아 점수를 오염시킨다."""
    return {w for w in _WORD.findall(text.lower()) if len(w) > 1}


def rank(items: Iterable[MemoryItem], query: str, limit: int = 10) -> list[MemoryItem]:
    """query 토큰이 content에 몇 개나 들어 있는지로 정렬. 모든 Memory 구현이 공유한다.

    부분 문자열 포함으로 센다 — 한국어는 교착어라 'uv를' != 'uv'로 단어 단위 비교가 거의 다 빗나간다.
    저장소(dict/SQLite/Redis)가 달라도 "무엇이 관련 있는가"의 판단은 하나여야 한다.
    """
    # ponytail: 전체 스캔 + 단순 겹침. 항목이 수천을 넘거나 의미 검색이 필요해지면
    # 같은 Memory 인터페이스로 VectorMemory를 붙인다 — 저장소별 전문검색(FTS5/tsvector)으로 흩지 말 것.
    words = _tokens(query)
    scored = [(sum(w in item.content.lower() for w in words), item) for item in items]
    hits = sorted((s for s in scored if s[0]), key=lambda s: -s[0])
    return [item for _, item in hits[:limit]]
