"""OpenAIProvider 변환 로직 단위 테스트 — 네트워크·API 키 불필요."""
from __future__ import annotations

from types import SimpleNamespace

from strata import ToolCall
from strata.providers.openai import _to_model_response
from strata.providers.openai import _to_openai_messages
from strata.providers.openai import _to_openai_tools
from strata.tools.base import Tool


class AddTool(Tool):
    name = 'add'
    description = 'Add two numbers'
    input_schema = {'type': 'object', 'properties': {'a': {'type': 'number'}}}

    async def execute(self, **kwargs):
        return kwargs['a']


def test_messages_round_trip():
    messages = [
        {'role': 'user', 'content': '1+2?'},
        {
            'role': 'assistant',
            'content': None,
            'tool_calls': [ToolCall(name='add', arguments={'a': 1, 'b': 2}, id='call_x')],
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
