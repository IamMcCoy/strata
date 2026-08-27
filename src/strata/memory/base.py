from __future__ import annotations

import math
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


# BM25 파라미터. k1은 빈도 포화(같은 단어가 더 나와도 점수가 무한히 오르지 않는다),
# b는 길이 정규화 강도. 정보검색에서 오래 검증된 기본값이라 튜닝 지점으로 열지 않는다.
_K1 = 1.5
_B = 0.75


def rank(items: Iterable[MemoryItem], query: str, limit: int = 10) -> list[MemoryItem]:
    """BM25로 관련성을 매긴다. 모든 Memory 구현이 공유한다 — 저장소가 달라도 판단은 하나여야 한다.

    단어 단위가 아니라 **부분 문자열**로 센다: 한국어는 교착어라 'uv를' != 'uv'로
    토큰 비교가 거의 다 빗나간다. 그래서 문서 길이의 단위도 토큰 수가 아니라 문자 수다.

    단순 겹침(질의 단어가 몇 개 들어 있나)을 쓰지 않는 이유: 점수의 최댓값이 질의 단어 수라
    3단어 질의면 값이 네 가지뿐이고, 동점이 대량 발생해 안정 정렬이 **삽입 순서**로 자른다.
    항목 10건에서도 "가장 관련 있는 것"이 아니라 "가장 먼저 저장된 것"이 나왔다.
    BM25는 빈도·문서 길이·단어의 희소성을 함께 보므로 점수가 연속값이 되어 그 붕괴가 사라진다.

    ponytail: 여전히 전체 스캔이고 의미 검색이 아니다 — '결제 실패'로 '구매 오류'를 찾지 못한다.
    동의어·의역이 필요해지면 같은 Memory 인터페이스로 VectorMemory를 붙인다.
    저장소별 전문검색(FTS5/tsvector)으로 흩지 말 것 — 구현마다 결과가 갈린다.
    """
    words = _tokens(query)
    items = list(items)
    if not words or not items:
        return []

    lowered = [item.content.lower() for item in items]
    counts = [{word: text.count(word) for word in words} for text in lowered]
    lengths = [len(text) or 1 for text in lowered]
    average = sum(lengths) / len(lengths)
    total = len(items)
    # 이 단어를 가진 항목 수 — 흔한 단어일수록 가중치가 낮아진다('작업'보다 '결제'가 무겁다)
    document_frequency = {word: sum(1 for count in counts if count[word]) for word in words}

    scored: list[tuple[float, MemoryItem]] = []
    for item, count, length in zip(items, counts, lengths):
        score = 0.0
        for word in words:
            frequency = count[word]
            if not frequency:
                continue
            appears = document_frequency[word]
            idf = math.log(1 + (total - appears + 0.5) / (appears + 0.5))
            score += idf * (frequency * (_K1 + 1)) / (
                frequency + _K1 * (1 - _B + _B * length / average)
            )
        if score:
            scored.append((score, item))

    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:limit]]
