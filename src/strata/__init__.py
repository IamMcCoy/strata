"""Strata — A composable runtime for agentic systems."""
from __future__ import annotations

import logging

from strata.agent.agent import Agent
from strata.agent.context import Context
from strata.conversation import trim_history
from strata.memory.base import Memory
from strata.memory.base import MemoryItem
from strata.memory.inmemory import InMemory
from strata.memory.redis import RedisMemory
from strata.memory.sqlite import SQLiteMemory
from strata.providers.anthropic import AnthropicProvider
from strata.providers.base import ModelResponse
from strata.providers.base import Provider
from strata.providers.base import ProviderError
from strata.providers.base import ToolCall
from strata.providers.fallback import FallbackProvider
from strata.providers.gemini import GeminiProvider
from strata.providers.openai import OpenAIProvider
from strata.runtime.config import RuntimeConfig
from strata.runtime.execution import ExecutionManager
from strata.runtime.execution import ExecutionNode
from strata.runtime.ids import new_run_id
from strata.runtime.runtime import BudgetExceeded
from strata.runtime.runtime import Cancelled
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy
from strata.strategies.react import REACT_PROMPT
from strata.strategies.react import ReActStrategy
from strata.strategies.recursive import RECURSIVE_PROMPT
from strata.strategies.recursive import RecursiveStrategy
from strata.strategies.reflection import REFLECTION_CRITIC_PROMPT
from strata.strategies.reflection import ReflectionStrategy
from strata.strategies.rlm import RLM_PROMPT
from strata.strategies.rlm import RLMStrategy
from strata.tools.base import Tool
from strata.tools.base import ToolEnv
from strata.tools.memory import MemoryTool
from strata.tools.python import PythonTool
from strata.tools.spawn import SpawnAgentTool

# 라이브러리는 로그를 설정하지 않는다 — 핸들러가 없을 때 조용하도록 NullHandler만 단다.
# 앱이 켠다: logging.basicConfig(level=logging.DEBUG)
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    'Agent',
    'AgentResult',
    'AnthropicProvider',
    'BudgetExceeded',
    'Cancelled',
    'Context',
    'ExecutionManager',
    'ExecutionNode',
    'FallbackProvider',
    'GeminiProvider',
    'InMemory',
    'Memory',
    'MemoryItem',
    'MemoryTool',
    'ModelResponse',
    'OpenAIProvider',
    'Provider',
    'ProviderError',
    'PythonTool',
    'REACT_PROMPT',
    'RECURSIVE_PROMPT',
    'REFLECTION_CRITIC_PROMPT',
    'RLMStrategy',
    'RLM_PROMPT',
    'ReActStrategy',
    'RecursiveStrategy',
    'ReflectionStrategy',
    'RedisMemory',
    'Runtime',
    'RuntimeConfig',
    'SQLiteMemory',
    'SpawnAgentTool',
    'Strategy',
    'Tool',
    'ToolCall',
    'ToolEnv',
    'trim_history',
    'new_run_id',
]
