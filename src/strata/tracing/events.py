"""Runtime lifecycle 이벤트 이름. Event dispatch는 Phase 6."""
from __future__ import annotations

AGENT_STARTED = 'agent.started'
AGENT_FINISHED = 'agent.finished'

STRATEGY_STARTED = 'strategy.started'
STRATEGY_FINISHED = 'strategy.finished'

PROVIDER_REQUEST = 'provider.request'
PROVIDER_RESPONSE = 'provider.response'

TOOL_STARTED = 'tool.started'
TOOL_FINISHED = 'tool.finished'

MEMORY_RETRIEVE = 'memory.retrieve'
MEMORY_STORE = 'memory.store'

AGENT_SPAWNED = 'agent.spawned'
AGENT_COMPLETED = 'agent.completed'

EXECUTION_FAILED = 'execution.failed'
