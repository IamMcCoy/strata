"""OpenAIProvider 변환 로직 단위 테스트 — 네트워크·API 키 불필요."""
from __future__ import annotations

from types import SimpleNamespace

from strata.providers import ToolCall
from strata.providers.openai import _to_model_response
from strata.providers.openai import _to_openai_messages
from strata.providers.openai import _to_openai_tools
from strata.tools import Tool


class AddTool(Tool):
    name = 'add'
    description = 'Add two numbers'
    input_schema = {'type': 'object', 'properties': {'a': {'type': 'number'}}}

    async def execute(self, env, **kwargs):
        return kwargs['a']


def test_messages_round_trip():
    messages = [
        {'role': 'user', 'content': '1+2?'},
        {
            'role': 'assistant',
            'content': None,
            # messages에는 ToolCall 객체가 아니라 dict가 담긴다 — 순수 JSON 계약 (ADR-0010)
            'tool_calls': [{'name': 'add', 'arguments': {'a': 1, 'b': 2}, 'id': 'call_x'}],
        },
        {'role': 'tool', 'name': 'add', 'tool_call_id': 'call_x', 'content': '3'},
    ]
    converted = _to_openai_messages(messages)
    assert converted[0] == {'role': 'user', 'content': '1+2?'}
    assert converted[1]['tool_calls'][0]['id'] == 'call_x'
    assert converted[1]['tool_calls'][0]['function']['name'] == 'add'
    assert converted[1]['tool_calls'][0]['function']['arguments'] == '{"a": 1, "b": 2}'
    assert converted[2] == {'role': 'tool', 'tool_call_id': 'call_x', 'content': '3'}


def test_tools_use_input_schema_as_parameters():
    (spec,) = _to_openai_tools([AddTool()])
    assert spec['type'] == 'function'
    assert spec['function']['name'] == 'add'
    assert spec['function']['parameters'] == AddTool.input_schema
    assert _to_openai_tools(None) is None


def test_response_converts_tool_calls_and_usage():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id='call_1',
                            function=SimpleNamespace(name='add', arguments='{"a": 1}'),
                        ),
                    ],
                ),
            ),
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    response = _to_model_response(completion)
    assert response.tool_calls == [ToolCall(name='add', arguments={'a': 1}, id='call_1')]
    # usage는 표준 키로 변환된다 (token budget 집계의 전제)
    assert response.usage == {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}


def test_response_without_tool_calls_is_final_text():
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='answer', tool_calls=None))],
        usage=None,
    )
    response = _to_model_response(completion)
    assert response.text == 'answer'
    assert response.tool_calls == []
    assert response.usage == {}


def test_reasoning_content_is_carried_out_of_the_response():
    """사고 모드가 실제로 켜졌는지는 reasoning_content 유무로만 확인된다.

    OpenAI SDK 모델에는 없는 필드지만 extra='allow'라 서버(vLLM 등)가 보낸 값이 객체에 붙어 온다.
    """
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='3입니다', tool_calls=None, reasoning_content='1+2를 계산한다',
                ),
            ),
        ],
        usage=None,
    )
    response = _to_model_response(completion)
    assert response.text == '3입니다', '사고가 답에 섞이면 안 된다'
    assert response.reasoning == '1+2를 계산한다'


def test_response_without_reasoning_leaves_the_field_none():
    """필드를 안 보내는 서버(순정 OpenAI)에서도 깨지지 않고, 사고 꺼짐과 구분된다."""
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='answer', tool_calls=None))],
        usage=None,
    )
    assert _to_model_response(completion).reasoning is None


def test_reasoning_tokens_are_extracted_from_usage_details():
    """순정 OpenAI(o-시리즈)는 사고 텍스트를 안 준다 — 이 숫자가 사고가 돌았다는 유일한 증거다."""
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='answer', tool_calls=None))],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=90, total_tokens=100,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=64),
        ),
    )
    usage = _to_model_response(completion).usage
    assert usage['reasoning_tokens'] == 64
    # total에 더하지 않는다 — completion_tokens 안에 이미 들어 있다
    assert usage['total_tokens'] == 100


def test_usage_without_reasoning_details_has_no_reasoning_key():
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='answer', tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )
    assert 'reasoning_tokens' not in _to_model_response(completion).usage
