from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeConfig:
    """실행 한도. 강제는 Strategy가 아닌 Runtime의 책임 (ADR-0004)."""

    max_depth: int = 5
    max_iterations: int = 30
    max_children: int = 8
    token_budget: int | None = None
    timeout: float | None = None  # 초 단위, run 전체 기준
