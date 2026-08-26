from __future__ import annotations

from typing import Any

from strata.memory.base import MemoryItem
from strata.tools.base import Tool
from strata.tools.base import ToolEnv


class MemoryTool(Tool):
    """실행 간 보존할 정보를 모델이 명시적으로 남기는 tool.

    store는 자동이 아니다 — 보존할 가치가 생긴 정보만 명시적으로 (ADR-0002).
    retrieve는 반대로 자동이다: Agent.run이 task로 조회해 instructions에 주입한다.
    """

    name = 'remember'
    description = (
        'Save a fact worth keeping for future runs (user preferences, stable conclusions). '
        'Do not save transient details of the current task — they are already in this conversation.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'content': {'type': 'string', 'description': 'The fact to remember, self-contained in one sentence'},
            'type': {
                'type': 'string',
                'enum': ['episodic', 'semantic', 'procedural'],
                'description': 'episodic = what happened, semantic = a fact, procedural = how to do something',
            },
        },
        'required': ['content'],
    }

    async def execute(self, env: ToolEnv, content: str = '', type: str = 'semantic', **kwargs: Any) -> Any:
        if env.runtime.memory is None:
            return 'No memory is configured for this agent; nothing was saved.'
        await env.runtime.memory.store(MemoryItem(content=content, type=type))
        return f'Remembered: {content}'
