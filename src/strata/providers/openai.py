from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from strata.providers.base import ModelResponse
from strata.providers.base import Provider
from strata.providers.base import ProviderError
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
                        'id': call.get('id') or f'call_{i}',
                        'type': 'function',
                        'function': {'name': call['name'], 'arguments': json.dumps(call['arguments'])},
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


def _usage(raw: Any) -> dict:
    """OpenAI usage → 표준 키. reasoning_tokens는 o-시리즈/gpt-5에서만 실린다.

    순정 OpenAI는 사고 **텍스트**를 절대 주지 않는다 — 이 숫자가 사고가 돌았다는 유일한 증거다.
    completion_tokens의 부분집합이므로 total에는 더하지 않는다.
    """
    if not raw:
        return {}
    usage = {
        'input_tokens': raw.prompt_tokens,
        'output_tokens': raw.completion_tokens,
        'total_tokens': raw.total_tokens,
    }
    details = getattr(raw, 'completion_tokens_details', None)
    if getattr(details, 'reasoning_tokens', None):
        usage['reasoning_tokens'] = details.reasoning_tokens
    return usage


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
    usage = _usage(getattr(completion, 'usage', None))
    return ModelResponse(
        text=message.content,
        tool_calls=tool_calls,
        usage=usage,
        # 비표준 확장 필드 — SDK 모델이 extra='allow'라 서버가 보낸 그대로 붙어 있다.
        # vLLM·DeepSeek는 reasoning_content, OpenRouter는 reasoning. 안 보내면 None.
        reasoning=getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None),
        raw=completion,
    )


async def _consume_stream(stream: Any, on_delta: Callable[[str], None] | None) -> ModelResponse:
    """스트리밍 청크를 모아 완결된 ModelResponse로 만든다.

    tool_calls는 조각으로 온다 — index별로 name과 arguments 문자열을 이어 붙여야 한다.
    usage는 마지막 청크에만 실린다(stream_options include_usage). 그 청크는 choices가 비어 있다.
    """
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    calls: dict[int, dict] = {}
    usage: dict = {}
    async for chunk in stream:
        if getattr(chunk, 'usage', None):
            usage = _usage(chunk.usage)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        # ponytail: 사고 조각은 on_delta로 흘리지 않는다 — on_delta는 "답"의 스트림이고
        # 여기에 섞으면 앱이 사고를 답으로 렌더한다. 필요하면 별도 콜백을 그때 판다.
        reasoning_delta = getattr(delta, 'reasoning_content', None) or getattr(delta, 'reasoning', None)
        if reasoning_delta:
            reasoning_parts.append(reasoning_delta)
        if getattr(delta, 'content', None):
            text_parts.append(delta.content)
            if on_delta is not None:
                on_delta(delta.content)
        for part in (getattr(delta, 'tool_calls', None) or []):
            call = calls.setdefault(part.index, {'id': None, 'name': '', 'arguments': ''})
            call['id'] = part.id or call['id']
            if part.function is not None:
                call['name'] = part.function.name or call['name']
                call['arguments'] += part.function.arguments or ''

    tool_calls = [
        ToolCall(name=c['name'], arguments=json.loads(c['arguments'] or '{}'), id=c['id'])
        for _, c in sorted(calls.items())
    ]
    return ModelResponse(
        text=''.join(text_parts) or None,
        tool_calls=tool_calls,
        usage=usage,
        reasoning=''.join(reasoning_parts) or None,
    )


class OpenAIProvider(Provider):
    """OpenAI 및 OpenAI-compatible API (vLLM, Ollama 등은 base_url만 지정).

    OpenAI-compatible 엔드포인트는 base_url만 바꾸면 그대로 동작한다 — 같은 코드다:

        vLLM        base_url='http://localhost:8000/v1'
        Ollama      base_url='http://localhost:11434/v1'
        OpenRouter  base_url='https://openrouter.ai/api/v1'
        Gemini      base_url='https://generativelanguage.googleapis.com/v1beta/openai/'

    api_key 우선순위: 명시적 인자 > OPENAI_API_KEY 환경변수.
    프레임워크는 키를 저장·로깅하지 않고 SDK에 전달만 한다.
    model_params: 기본 샘플링 파라미터(temperature, max_tokens 등) — 합치기는 Runtime.generate가 한다.
    max_retries: 429·5xx·연결 오류를 SDK가 지수 백오프로 재시도하는 횟수(기본 2 = 총 3회 시도).
    코어에 재시도 계층을 겹치지 않는 이유는 백오프가 곱해지기 때문이다 (ADR-0012).
    긴 재귀 실행에서 한 번의 rate limit으로 전체를 잃고 싶지 않으면 올린다.
    **주의**: 총 대기 시간은 대략 max_retries × timeout이다 — 둘을 같이 정한다.
    나머지 client_kwargs(timeout 등)는 AsyncOpenAI 생성자로 간다.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int = 2,
        model_params: dict[str, Any] | None = None,
        **client_kwargs: Any,
    ):
        try:
            from openai import AsyncOpenAI
            import openai as _openai
            self._api_error = _openai.APIError
        except ImportError as exc:  # 코어는 의존성 0 — openai는 optional extra
            raise ImportError(
                "OpenAIProvider requires the openai package: uv add 'strata[openai]'",
            ) from exc
        self.model = model
        self.model_params = dict(model_params or {})
        self.client = AsyncOpenAI(
            api_key=api_key or os.environ.get('OPENAI_API_KEY'),
            base_url=base_url,
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
        request: dict[str, Any] = {
            'model': self.model,
            'messages': _to_openai_messages(messages),
            **kwargs,
        }
        openai_tools = _to_openai_tools(tools)
        if openai_tools:
            request['tools'] = openai_tools
        if on_delta is None:
            # 스트리밍이 필요 없으면 굳이 쓰지 않는다 — 응답이 한 번에 오고 usage도 그냥 실린다
            return _to_model_response(await self.client.chat.completions.create(**request))
        # include_usage: 스트리밍에서는 마지막 청크에만 usage가 실린다. 없으면 token_budget이 0으로 샌다.
        request['stream'] = True
        request['stream_options'] = {'include_usage': True}
        # async with로 닫는다 — 끝까지 순회해도 HTTP 응답은 자동으로 닫히지 않는다.
        # 안 닫으면 스트리밍 호출마다 커넥션이 새고 GC 시점에 finalizer가 터진다.
        async with await self.client.chat.completions.create(**request) as stream:
            return await _consume_stream(stream, on_delta)
