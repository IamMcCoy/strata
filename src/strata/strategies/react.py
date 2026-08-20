from __future__ import annotations

from strata.agent.context import Context
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy


class ReActStrategy(Strategy):
    """Tool을 반복 사용하며 문제를 해결하는 최소 tool calling loop.

    tool call 파싱은 Provider가 ModelResponse.tool_calls로 흡수하므로
    여기서는 Provider별 형식을 모른다.
    """

    async def execute(self, context: Context, runtime: Runtime) -> AgentResult:
        for _ in range(runtime.config.max_iterations):
            response = await runtime.provider.generate(
                context.messages,
                tools=list(runtime.tools.values()),
            )
            context.messages.append({
                'role': 'assistant',
                'content': response.text,
                'tool_calls': response.tool_calls,
            })

            if not response.tool_calls:
                return AgentResult(result=response.text)

            for call in response.tool_calls:
                result = await runtime.execute_tool(call.name, call.arguments)
                context.add_tool_result(result)
                context.messages.append({
                    'role': 'tool',
                    'name': call.name,
                    'tool_call_id': call.id,
                    'content': str(result),
                })

        return AgentResult(status='budget_exceeded')
