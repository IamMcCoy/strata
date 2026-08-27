from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from types import MappingProxyType
from typing import Any

from strata.runtime.config import validate_limits


@dataclass
class AgentResult:
    """Child → Parent 결과 계약. 전체 Context가 아닌 이 형태만 parent에 전달된다."""

    status: str = 'completed'  # completed | failed | budget_exceeded | cancelled
    result: str | None = None
    evidence: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class Strategy(ABC):
    """실행 패턴의 abstraction — 프레임워크의 핵심 확장 포인트 (ADR-0003).

    Provider/Tool/Memory/Child Agent에는 runtime의 primitive를 통해서만 접근한다.
    """

    # 이 전략이 제안하는 실행 한도(RuntimeConfig의 필드 이름). 강제는 여전히 Runtime이 하고,
    # 사용자가 RuntimeConfig에 명시한 값이 이긴다 (ADR-0014). 클래스 기본값은 읽기 전용 —
    # super().__init__을 부르지 않는 서브클래스가 공유 dict를 건드리지 못하게.
    limits: Mapping[str, Any] = MappingProxyType({})

    def __init__(self, **limits: Any):
        """전략별 한도를 생성 시점에 받는다 — `ReActStrategy(max_iterations=10)`.

        이름은 RuntimeConfig의 필드여야 한다(오타는 여기서 TypeError). None은 무시한다.
        """
        if limits:
            self.limits = validate_limits(limits)

    @abstractmethod
    async def execute(self, context, runtime) -> AgentResult: ...
