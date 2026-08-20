from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from strata.strategies.base import AgentResult


@dataclass
class ExecutionNode:
    """실행 tree의 한 노드. 초기 In-Memory 구현 (ADR-0005)."""

    id: str
    parent_id: str | None = None
    task: str = ''
    depth: int = 0
    status: str = 'running'  # running | completed | failed | budget_exceeded
    result: AgentResult | None = None
    children: list[ExecutionNode] = field(default_factory=list)
