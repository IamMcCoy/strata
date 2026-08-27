from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strata.agent.context import Context
    from strata.runtime.runtime import Runtime


@dataclass
class ToolEnv:
    """Tool 실행 환경 — 호출한 agent의 Context와 run의 Runtime.

    대부분의 Tool은 무시한다. Runtime primitive가 필요한 Tool(REPL, spawn 등)은
    env.runtime.spawn_agent() / env.context.variables 등에 접근한다 —
    Tool이 Runtime 통제 밖에서 동작하지 않게 하는 유일한 경로다.
    """

    context: Context
    runtime: Runtime


class Tool(ABC):
    """외부 시스템·환경과의 상호작용. Provider/Strategy에 종속되지 않는다.

    execute의 첫 인자는 항상 ToolEnv, 나머지는 모델이 input_schema에 맞춰 넘긴 인자.
    """

    name: str
    description: str
    input_schema: dict

    @abstractmethod
    async def execute(self, env: ToolEnv, **kwargs: Any) -> Any: ...
