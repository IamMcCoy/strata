from __future__ import annotations

import json
import os
from typing import Any

from strata.providers.base import ModelResponse
from strata.providers.base import Provider
from strata.providers.base import ToolCall
from strata.tools.base import Tool


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Strata 범용 메시지 → OpenAI chat 형식. 변환 책임은 Provider에 있다."""
    converted: list[dict] = []
    for message in messages:
        role = message['role']
        if role == 'assistant':
            entry: dict[str, Any] = {'role': 'assistant', 'content': message.get('content')}
            tool_calls = message.get('tool_calls') or []
            if tool_calls:
                entry['tool_calls'] = [
                    {
                        # id 없는 fake 응답도 왕복되도록 결정적 fallback
                        'id': call.id or f'call_{i}',
                        'type': 'function',
                        'function': {'name': call.name, 'arguments': json.dumps(call.arguments)},
                    }
                    for i, call in enumerate(tool_calls)
                ]
            converted.append(entry)
        elif role == 'tool':
            converted.append({
                'role': 'tool',
                'tool_call_id': message.get('tool_call_id') or 'call_0',
                'content': message['content'],
            })
        else:
            converted.append({'role': role, 'content': message['content']})
    return converted


def _to_openai_tools(tools: list[Tool] | None) -> list[dict] | None:
    """Tool.input_schema(JSON Schema) → OpenAI function tool 형식."""
    if not tools:
        return None
    return [
        {
            'type': 'function',
            'function': {
                'name': tool.name,
                'description': tool.description,
                'parameters': tool.input_schema,
            },
        }
        for tool in tools
    ]


def _to_model_response(completion: Any) -> ModelResponse:
    """OpenAI 응답 → ModelResponse. usage는 표준 키로 변환한다."""
    message = completion.choices[0].message
    tool_calls = [
        ToolCall(
            name=call.function.name,
            arguments=json.loads(call.function.arguments or '{}'),
            id=call.id,
        )
        for call in (message.tool_calls or [])
    ]
    usage: dict = {}
    if getattr(completion, 'usage', None):
        usage = {
            'input_tokens': completion.usage.prompt_tokens,
            'output_tokens': completion.usage.completion_tokens,
            'total_tokens': completion.usage.total_tokens,
        }
    return ModelResponse(text=message.content, tool_calls=tool_calls, usage=usage, raw=completion)


class OpenAIProvider(Provider):
    """OpenAI 및 OpenAI-compatible API (vLLM, Ollama 등은 base_url만 지정).

    api_key 우선순위: 명시적 인자 > OPENAI_API_KEY 환경변수.
    프레임워크는 키를 저장·로깅하지 않고 SDK에 전달만 한다.
    model_params: 기본 샘플링 파라미터(temperature, max_tokens 등) — 합치기는 Runtime.generate가 한다.
    client_kwargs는 AsyncOpenAI 생성자로 간다.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model_params: dict[str, Any] | None = None,
        **client_kwargs: Any,
    ):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # 코어는 의존성 0 — openai는 optional extra
            raise ImportError(
                "OpenAIProvider requires the openai package: uv add 'strata[openai]'",
            ) from exc
        self.model = model
        self.model_params = dict(model_params or {})
        self.client = AsyncOpenAI(
            api_key=api_key or os.environ.get('OPENAI_API_KEY'),
            base_url=base_url,
            **client_kwargs,
        )

    async def generate(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        request: dict[str, Any] = {
            'model': self.model,
            'messages': _to_openai_messages(messages),
            **kwargs,
        }
        openai_tools = _to_openai_tools(tools)
        if openai_tools:
            request['tools'] = openai_tools
        completion = await self.client.chat.completions.create(**request)
        return _to_model_response(completion)
