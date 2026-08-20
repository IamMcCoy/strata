from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass
class Context:
    """현재 실행의 상태. 실행 종료 후 지속을 보장하지 않는다 — 영속은 Memory의 몫."""

    messages: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    tool_results: list = field(default_factory=list)
    child_results: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def add_tool_result(self, result):
        self.tool_results.append(result)

    def add_child_result(self, result):
        self.child_results.append(result)
