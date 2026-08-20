from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import Any


class Tool(ABC):
    """외부 시스템·환경과의 상호작용. Provider/Strategy에 종속되지 않는다."""

    name: str
    description: str
    input_schema: dict

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any: ...
