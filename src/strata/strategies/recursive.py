from __future__ import annotations

from strata.strategies.react import REACT_PROMPT
from strata.strategies.react import ReActStrategy
from strata.tools.spawn import SpawnAgentTool

RECURSIVE_PROMPT = REACT_PROMPT + """

# Delegating to child agents
You have a `spawn_agent` tool that runs a subtask in a fresh child agent and returns only its final answer.

## What the child sees
- The child does not see this conversation — no earlier messages, tool results, or your reasoning. \
It starts from the `task` string (plus the optional `context` string) and nothing else.
- Therefore write every task as a self-contained brief: the goal, all inputs it needs (paste them or \
pass them as `context`), the exact output format you want back, and any constraints. If you would \
need to say "as discussed above", the child cannot do the job.

## When to delegate
- Delegate work that is independent of your current state and sizeable enough to be worth a fresh \
context: separable subproblems, parallel investigations, processing a slice of data you hand over as `context`.
- Do not delegate trivial steps you can do directly, work that depends on your conversation history, \
or the whole original task restated — that only recurses without progress.
- Depth and the number of children per agent are limited. Decompose into a few meaningful pieces, not many tiny ones.

## Reading the result
- The observation carries `status` and `result`. `completed` → use `result`. `failed` or \
`budget_exceeded` → do not simply retry the same call; use any partial `result`, narrow the task, \
or do that part yourself. If the metadata says `max_depth` or `max_children`, stop delegating and finish \
with what you have.
- Verify child answers against each other and against your own evidence before combining them; \
children can be wrong or incomplete. Your final answer is a synthesis, not a concatenation."""


class RecursiveStrategy(ReActStrategy):
    """재귀 위임 패턴: ReAct loop + spawn_agent tool.

    child는 기본적으로 같은 RecursiveStrategy를 상속받아 다시 재귀할 수 있고,
    깊이·자식 수·예산 한도는 Runtime이 강제한다 — 한도 초과 시 모델은
    budget_exceeded 관찰을 받고 스스로 답해야 한다.
    """

    description = (
        'Break the task into a few independent sub-problems, each solved by a child agent '
        'that starts from a fresh context.'
    )
    default_tools = (SpawnAgentTool(),)
    prompt = RECURSIVE_PROMPT
