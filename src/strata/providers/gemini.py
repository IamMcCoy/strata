from __future__ import annotations

import base64
import os
from collections.abc import Callable
from typing import Any

from strata.providers.base import ModelResponse
from strata.providers.base import Provider
from strata.providers.base import ProviderError
from strata.providers.base import ToolCall
from strata.tools.base import Tool


def _to_gemini_contents(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Strata 범용 메시지 → Gemini contents. 변환 책임은 Provider에 있다.

    OpenAI와 다른 세 가지:
      1. system은 메시지가 아니라 config.system_instruction이다 (Anthropic과 같다).
      2. assistant가 아니라 **role='model'** 이다.
      3. tool 호출/결과가 role이 아니라 **part**다 — function_call / function_response.
    """
    system: str | None = None
    contents: list[dict] = []
    for message in messages:
        role = message['role']
        if role == 'system':
            system = message['content']
        elif role == 'assistant':
            parts: list[dict] = []
            if message.get('content'):
                parts.append({'text': message['content']})
            for index, call in enumerate(message.get('tool_calls') or []):
                part: dict[str, Any] = {
                    'function_call': {
                        'id': call.get('id') or f'call_{index}',   # id 없는 fake 응답도 왕복되게
                        'name': call['name'],
                        'args': call['arguments'],
                    },
                }
                # Gemini 3.x는 이 서명을 돌려받지 못하면 400으로 거절한다.
                # provider_state에는 base64 문자열로 담겨 있다(messages는 순수 JSON) — bytes로 되돌린다.
                signature = (call.get('provider_state') or {}).get('thought_signature')
                if signature:
                    part['thought_signature'] = base64.b64decode(signature)
                parts.append(part)
            if parts:
                contents.append({'role': 'model', 'parts': parts})
        elif role == 'tool':
            part = {
                'function_response': {
                    'id': message.get('tool_call_id') or 'call_0',
                    'name': message.get('name') or 'tool',
                    # response는 반드시 dict여야 한다 — 문자열 관찰을 감싼다
                    'response': {'result': str(message['content'])},
                },
            }
            # 연속된 tool 결과는 한 user 턴으로 묶는다 (Anthropic과 같은 이유)
            if contents and contents[-1]['role'] == 'user' and 'function_response' in contents[-1]['parts'][0]:
                contents[-1]['parts'].append(part)
            else:
                contents.append({'role': 'user', 'parts': [part]})
        else:
            contents.append({'role': 'user', 'parts': [{'text': message['content']}]})
    return system, contents


def _to_gemini_tools(tools: list[Tool] | None) -> list[dict] | None:
    """Tool.input_schema(JSON Schema) → Gemini function declaration.

    parameters(Gemini 전용 Schema)가 아니라 parameters_json_schema를 쓴다 —
    input_schema가 이미 JSON Schema라 변환 코드가 통째로 필요 없다.
    """
    if not tools:
        return None
    return [{
        'function_declarations': [
            {
                'name': tool.name,
                'description': tool.description,
                'parameters_json_schema': tool.input_schema,
            }
            for tool in tools
        ],
    }]


def _usage(raw: Any) -> dict:
    """Gemini usage_metadata → 표준 키. token_budget 집계의 전제다."""
    meta = getattr(raw, 'usage_metadata', None)
    if meta is None:
        return {}
    incoming = meta.prompt_token_count or 0
    outgoing = meta.candidates_token_count or 0
    return {
        'input_tokens': incoming,
        'output_tokens': outgoing,
        'total_tokens': meta.total_token_count or (incoming + outgoing),
    }


def _parts_of(response: Any) -> list:
    candidates = getattr(response, 'candidates', None) or []
    if not candidates:
        return []
    content = getattr(candidates[0], 'content', None)
    return getattr(content, 'parts', None) or []


def _collect(parts: list, texts: list[str], calls: list[ToolCall]) -> None:
    """한 응답(또는 스트림 청크)의 part들을 텍스트와 tool 호출로 가른다."""
    for part in parts:
        if getattr(part, 'text', None):
            texts.append(part.text)
        call = getattr(part, 'function_call', None)
        if call is not None:
            # ponytail: function_call은 청크 하나에 온전히 온다고 본다. partial_args가 실제로
            # 쪼개져 오면 그때 index별 누적을 단다(OpenAI 쪽 _consume_stream처럼).
            state: dict = {}
            signature = getattr(part, 'thought_signature', None)
            if signature:
                # bytes는 JSON에 못 담는다 — base64로 옮겨 messages를 순수 JSON으로 유지한다
                state['thought_signature'] = base64.b64encode(signature).decode()
            calls.append(
                ToolCall(
                    name=call.name, arguments=dict(call.args or {}), id=call.id, provider_state=state,
                ),
            )


class GeminiProvider(Provider):
    """Gemini 네이티브. `client.aio.models.generate_content(_stream)` 위에 올린다.

    `client.interactions`(agents/environments/webhooks와 함께 있는 next-gen API)를 쓰지 않는
    이유는 그것이 **구글의 agent 실행 API**이기 때문이다 — strata와 같은 층의 추상화라
    Provider로 감싸면 Runtime의 한도·usage·재귀 제어가 구글 쪽 상태와 이중으로 겹친다.
    Provider가 필요로 하는 것은 무상태 완성 호출이고 그건 generate_content다 (ADR-0012).

    OpenAI 호환 엔드포인트(`OpenAIProvider(base_url=...)`)도 여전히 유효하다 —
    빠르게 붙일 때 쓰고, 네이티브 기능이 필요하면 이 클래스를 쓴다.

    api_key 우선순위: 명시적 인자 > GEMINI_API_KEY > GOOGLE_API_KEY.
    max_retries: 다른 Provider와 같은 이름·같은 기본값(2). Gemini SDK는 재시도가 아니라
    **총 시도 횟수**(attempts)를 받으므로 +1로 변환한다 — 안 그러면 같은 값이 벤더마다
    다르게 동작한다.

    검증됨: gemini-3.5-flash-lite로 스트리밍·tool 왕복·usage 집계까지 실제 호출로 확인했다.

    Gemini 3.x는 function_call part의 `thought_signature`를 다음 턴에 돌려받아야 한다 —
    없으면 400으로 거절한다. bytes라 messages(순수 JSON)에 직접 못 담으므로
    `ToolCall.provider_state`에 base64로 실어 왕복시킨다.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_retries: int = 2,
        model_params: dict[str, Any] | None = None,
        **client_kwargs: Any,
    ):
        try:
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types
            self._api_error = genai_errors.APIError
        except ImportError as exc:  # 코어는 의존성 0 — google-genai는 optional extra
            raise ImportError(
                "GeminiProvider requires the google-genai package: uv add 'strata[gemini]'",
            ) from exc
        self.model = model
        self.model_params = dict(model_params or {})
        self._types = types
        http_options = types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=max_retries + 1),
        )
        self.client = genai.Client(
            api_key=api_key or os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'),
            http_options=http_options,
            **client_kwargs,
        )

    def _config(self, system: str | None, tools: list[Tool] | None, kwargs: dict) -> Any:
        config: dict[str, Any] = dict(kwargs)
        if system:
            config['system_instruction'] = system
        gemini_tools = _to_gemini_tools(tools)
        if gemini_tools:
            config['tools'] = gemini_tools
        return self._types.GenerateContentConfig(**config) if config else None

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
        system, contents = _to_gemini_contents(messages)
        request = {
            'model': self.model,
            'contents': contents,
            'config': self._config(system, tools, kwargs),
        }
        texts: list[str] = []
        calls: list[ToolCall] = []

        if on_delta is None:
            response = await self.client.aio.models.generate_content(**request)
            _collect(_parts_of(response), texts, calls)
            return ModelResponse(
                text=''.join(texts) or None, tool_calls=calls, usage=_usage(response), raw=response,
            )

        usage: dict = {}
        stream = await self.client.aio.models.generate_content_stream(**request)
        async for chunk in stream:
            before = len(texts)
            _collect(_parts_of(chunk), texts, calls)
            for text in texts[before:]:
                on_delta(text)
            # usage는 청크마다 누적본으로 온다 — 마지막 값이 최종이다
            if _usage(chunk):
                usage = _usage(chunk)
        return ModelResponse(text=''.join(texts) or None, tool_calls=calls, usage=usage)
