from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field


@dataclass
class AgentResult:
    """Child → Parent 결과 계약. 전체 Context가 아닌 이 형태만 parent에 전달된다."""

    status: str = 'completed'  # completed | failed | budget_exceeded
    result: str | None = None
    evidence: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class Strategy(ABC):
    """실행 패턴의 abstraction — 프레임워크의 핵심 확장 포인트 (ADR-0003).

    Provider/Tool/Memory/Child Agent에는 runtime의 primitive를 통해서만 접근한다.
    """

    @abstractmethod
    async def execute(self, context, runtime) -> AgentResult: ...
