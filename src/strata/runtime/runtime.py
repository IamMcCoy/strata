from __future__ import annotations

from typing import Any

from strata.runtime.config import RuntimeConfig
from strata.strategies.base import AgentResult


class Runtime:
    """Agent 실행의 공통 환경: registry, spawn, 실행 한도, 이벤트.

    인스턴스는 run당 하나 — token budget, Execution Tree 등 run 전역 상태를
    담으며 child agent는 spawn을 통해 이를 공유한다 (ADR-0006).
    Strategy는 이 클래스가 제공하는 primitive를 통해서만
    Provider/Tool/Memory/Child Agent에 접근한다.
    """

    def __init__(self, provider=None, tools=None, memory=None, config=None):
        self.provider = provider
        self.tools = {t.name: t for t in (tools or [])}
        self.memory = memory
        self.config = config or RuntimeConfig()

    async def spawn_agent(
        self,
        task: str,
        parent_context: Any,
        strategy: Any = None,
        provider: Any = None,
    ) -> AgentResult:
        """Child Agent 생성·실행. 미지정 인자는 parent 것을 상속한다."""
        raise NotImplementedError  # Phase 3 — Recursive / RLM

    async def execute_tool(self, name: str, arguments: dict) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            # ponytail: 예외 대신 관찰 문자열 반환 — 모델이 잘못된 tool 이름에서 회복하게
            return f"Tool '{name}' not found. Available: {sorted(self.tools)}"
        return await tool.execute(**arguments)
