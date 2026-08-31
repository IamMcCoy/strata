from __future__ import annotations

import itertools
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Runtime은 Strategy를 몰라도 된다 — 타입 힌트로만 쓰므로 런타임 import를 피한다.
    # (없으면 strategies/__init__.py ↔ runtime 순환 import가 난다)
    from strata.strategies.base import AgentResult

# reasoning_tokens는 **참고용 내역**이다 — 여기서 total에 더하지 않는다(벤더가 이미 반영했다.
# OpenAI는 completion_tokens 안에, Gemini는 total_token_count 안에 넣어 준다). 이중 계상 금지.
# 별도 키인 이유는 사고 모드가 실제로 켜졌는지의 유일한 벤더 중립 증거이기 때문이다:
# OpenAI 순정은 사고 텍스트를 아예 안 주고 이 숫자만 준다.
USAGE_KEYS = ('input_tokens', 'output_tokens', 'total_tokens', 'reasoning_tokens')


@dataclass
class ExecutionNode:
    """실행 tree의 한 노드. 초기 In-Memory 구현 (ADR-0005)."""

    id: str
    parent_id: str | None = None
    task: str = ''
    depth: int = 0
    status: str = 'running'  # running | completed | failed | budget_exceeded | cancelled
    result: AgentResult | None = None
    iterations: int = 0  # 이 노드의 provider 호출 횟수 — max_iterations 집계 단위
    # 이 노드가 직접 쓴 토큰. run 전체 합계는 Runtime.usage에 따로 있다 —
    # 재귀에서 "어느 가지가 비쌌나"는 노드별로만 알 수 있다.
    usage: dict[str, int] = field(default_factory=lambda: dict.fromkeys(USAGE_KEYS, 0))
    children: list[ExecutionNode] = field(default_factory=list)

    def subtree_usage(self) -> dict[str, int]:
        """자신 + 모든 자손의 토큰 합. child를 여럿 띄운 가지의 진짜 비용이다."""
        total = dict(self.usage)
        for child in self.children:
            for key, amount in child.subtree_usage().items():
                total[key] += amount
        return total


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
