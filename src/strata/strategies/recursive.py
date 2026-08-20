from __future__ import annotations

from strata.strategies.react import ReActStrategy
from strata.tools.spawn import SpawnAgentTool


class RecursiveStrategy(ReActStrategy):
    """재귀 위임 패턴: ReAct loop + spawn_agent tool.

    child는 기본적으로 같은 RecursiveStrategy를 상속받아 다시 재귀할 수 있고,
    깊이·자식 수·예산 한도는 Runtime이 강제한다 — 한도 초과 시 모델은
    budget_exceeded 관찰을 받고 스스로 답해야 한다.
    """

    default_tools = (SpawnAgentTool(),)
