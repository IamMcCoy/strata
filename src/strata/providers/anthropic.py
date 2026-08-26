from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from strata.providers.base import ModelResponse
from strata.providers.base import Provider
from strata.providers.base import ProviderError
from strata.providers.base import ToolCall
from strata.tools.base import Tool


def _to_anthropic_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Strata 범용 메시지 → Anthropic 형식. 변환 책임은 Provider에 있다.

    OpenAI와 근본적으로 다른 세 가지:
      1. system은 메시지가 아니라 최상위 파라미터다.
      2. tool 호출/결과가 role이 아니라 **content block**이다.
      3. tool 결과는 role='tool'이 아니라 role='user'의 tool_result 블록으로 들어간다.
    """
    system: str | None = None
    converted: list[dict] = []
    for message in messages:
        role = message['role']
        if role == 'system':
            system = message['content']
        elif role == 'assistant':
            blocks: list[dict] = []
            if message.get('content'):
                blocks.append({'type': 'text', 'text': message['content']})
            for index, call in enumerate(message.get('tool_calls') or []):
                blocks.append({
                    'type': 'tool_use',
                    'id': call.get('id') or f'call_{index}',   # id 없는 fake 응답도 왕복되게
                    'name': call['name'],
                    'input': call['arguments'],
                })
            if blocks:
                converted.append({'role': 'assistant', 'content': blocks})
        elif role == 'tool':
            block = {
                'type': 'tool_result',
                'tool_use_id': message.get('tool_call_id') or 'call_0',
                'content': str(message['content']),
            }
            # 연속된 tool 결과는 한 user 메시지로 묶는다 — Anthropic은 그렇게 기대한다
            if converted and converted[-1]['role'] == 'user' and isinstance(converted[-1]['content'], list):
                converted[-1]['content'].append(block)
            else:
                converted.append({'role': 'user', 'content': [block]})
        else:
            converted.append({'role': role, 'content': message['content']})
    return system, converted


def _to_anthropic_tools(tools: list[Tool] | None) -> list[dict] | None:
    """Tool.input_schema(JSON Schema) → Anthropic tool 형식."""
    if not tools:
        return None
    return [
        {'name': tool.name, 'description': tool.description, 'input_schema': tool.input_schema}
        for tool in tools
    ]


def _usage(raw: Any) -> dict:
    """Anthropic은 total을 주지 않는다 — token_budget 집계를 위해 여기서 만든다."""
    if not getattr(raw, 'usage', None):
        return {}
    incoming, outgoing = raw.usage.input_tokens, raw.usage.output_tokens
    return {'input_tokens': incoming, 'output_tokens': outgoing, 'total_tokens': incoming + outgoing}


def _to_model_response(message: Any) -> ModelResponse:
    text = ''.join(block.text for block in message.content if block.type == 'text') or None
    tool_calls = [
        ToolCall(name=block.name, arguments=dict(block.input), id=block.id)
        for block in message.content if block.type == 'tool_use'
    ]
    return ModelResponse(text=text, tool_calls=tool_calls, usage=_usage(message), raw=message)


class AnthropicProvider(Provider):
    """Claude. OpenAI와 메시지 형식이 근본적으로 달라 별도 구현이다 (OpenAI-compatible이 아니다).

    api_key 우선순위: 명시적 인자 > ANTHROPIC_API_KEY 환경변수.
    프레임워크는 키를 저장·로깅하지 않고 SDK에 전달만 한다.

    max_tokens는 Anthropic이 **필수**로 요구한다 — 기본값을 두되 model_params로 덮을 수 있다.
    max_retries: OpenAIProvider와 같은 이름·같은 기본값(2). SDK가 429·5xx를 지수 백오프로
    재시도한다. 총 대기 시간은 대략 max_retries × timeout이다 (ADR-0012).

    **미검증**: 이 Provider는 실제 Anthropic API로 호출해본 적이 없다. 메시지 변환은
    단위 테스트(`tests/test_anthropic_provider.py`)로 고정돼 있지만 스트리밍 경로와
    실제 tool 왕복은 확인되지 않았다.
    """

    def __init__(
        self,
        model: str = 'claude-sonnet-5',
        api_key: str | None = None,
        max_tokens: int = 4096,
        max_retries: int = 2,
        model_params: dict[str, Any] | None = None,
        **client_kwargs: Any,
    ):
        try:
            from anthropic import AsyncAnthropic
            import anthropic as _anthropic
            self._api_error = _anthropic.APIError
        except ImportError as exc:  # 코어는 의존성 0 — anthropic은 optional extra
            raise ImportError(
                "AnthropicProvider requires the anthropic package: uv add 'strata[anthropic]'",
            ) from exc
        self.model = model
        self.max_tokens = max_tokens
        self.model_params = dict(model_params or {})
        self.client = AsyncAnthropic(
            api_key=api_key or os.environ.get('ANTHROPIC_API_KEY'),
            max_retries=max_retries,
            **client_kwargs,
        )

    async def generate(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        on_delta: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """SDK 예외를 ProviderError로 번역한다 — 코어가 벤더를 몰라도 인프라 오류를 가른다 (ADR-0013).

        재시도는 SDK가 이미 했다. 여기 오는 건 재시도까지 소진된 상태다.
        """
        try:
            return await self._call(messages, tools=tools, on_delta=on_delta, **kwargs)
        except self._api_error as exc:
            raise ProviderError(f'{type(exc).__name__}: {exc}') from exc

    async def _call(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        on_delta: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        system, converted = _to_anthropic_messages(messages)
        request: dict[str, Any] = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'messages': converted,
            **kwargs,
        }
        if system:
            request['system'] = system
        anthropic_tools = _to_anthropic_tools(tools)
        if anthropic_tools:
            request['tools'] = anthropic_tools

        if on_delta is None:
            return _to_model_response(await self.client.messages.create(**request))
        # SDK의 stream 헬퍼가 블록 누적을 대신 해준다 — get_final_message()가 완결 응답을 준다.
        # 그래서 반환 계약이 스트리밍 여부와 무관하게 같다 (ADR-0012).
        async with self.client.messages.stream(**request) as stream:
            async for text in stream.text_stream:
                on_delta(text)
            return _to_model_response(await stream.get_final_message())
