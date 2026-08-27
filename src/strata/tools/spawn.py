from __future__ import annotations

from typing import Any

from strata.tools.base import Tool
from strata.tools.base import ToolEnv


class SpawnAgentTool(Tool):
    """child agent 위임 tool. 트리거는 Tool, 메커니즘은 runtime.spawn_agent (ADR-0007).

    한도 검사·Execution Tree 등록은 spawn_agent 안에서 일어나므로 Tool 형태여도
    Runtime 통제 안이다. 결과 계약(status/result)만 관찰로 돌려준다.
    """

    name = 'spawn_agent'
    description = (
        'Delegate a subtask to a child agent that works in a fresh, independent context '
        'and returns only its final answer. Optionally pass `context` (e.g. a slice of '
        'data) — the child sees it as its own `context` variable, not this conversation.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'task': {'type': 'string', 'description': 'The subtask for the child agent'},
            'context': {'type': 'string', 'description': 'Optional sub-context handed to the child'},
        },
        'required': ['task'],
    }

    async def execute(self, env: ToolEnv, task: str = '', context: Any = None, **kwargs: Any) -> Any:
        result = await env.runtime.spawn_agent(task, env.context, context=context)
        observation: dict[str, Any] = {'status': result.status, 'result': result.result}
        if result.status != 'completed':
            observation['metadata'] = result.metadata
        return observation
