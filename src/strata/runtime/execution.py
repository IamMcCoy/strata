from __future__ import annotations

import itertools
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
    iterations: int = 0  # 이 노드의 provider 호출 횟수 — max_iterations 집계 단위
    children: list[ExecutionNode] = field(default_factory=list)


class ExecutionManager:
    """run 하나의 Execution Tree. In-Memory (ADR-0005), run당 하나 (ADR-0006)."""

    def __init__(self) -> None:
        self.nodes: dict[str, ExecutionNode] = {}
        self.root: ExecutionNode | None = None
        self._ids = itertools.count()

    def open(self, task: str, parent_id: str | None = None) -> ExecutionNode:
        parent = self.nodes[parent_id] if parent_id is not None else None
        node = ExecutionNode(
            id=f'exec_{next(self._ids)}',
            parent_id=parent.id if parent else None,
            task=task,
            depth=parent.depth + 1 if parent else 0,
        )
        self.nodes[node.id] = node
        if parent:
            parent.children.append(node)
        else:
            self.root = node
        return node

    def close(self, node_id: str, result: AgentResult) -> None:
        node = self.nodes[node_id]
        node.status = result.status
        node.result = result
