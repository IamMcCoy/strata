"""AnthropicProvider — 메시지 변환. 실제 API 호출 없음.

OpenAI와 근본적으로 다른 세 지점을 고정한다: system은 최상위 파라미터,
tool 호출/결과는 content block, tool 결과는 role='user'.
"""
from __future__ import annotations

from types import SimpleNamespace

from strata import Tool
from strata.providers.anthropic import _to_anthropic_messages
from strata.providers.anthropic import _to_anthropic_tools
from strata.providers.anthropic import _to_model_response


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers'
    input_schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}}, 'required': ['a']}

    async def execute(self, env, **kwargs):
        return kwargs['a']


def test_system_is_lifted_out_of_messages():
    """Anthropic은 system을 메시지로 받지 않는다 — 최상위 파라미터다."""
    system, converted = _to_anthropic_messages([
        {'role': 'system', 'content': '너는 조수다'},
        {'role': 'user', 'content': '안녕'},
    ])
    assert system == '너는 조수다'
    assert converted == [{'role': 'user', 'content': '안녕'}]


def test_tool_calls_become_content_blocks():
    _, converted = _to_anthropic_messages([
        {'role': 'user', 'content': '더해줘'},
        {
            'role': 'assistant', 'content': None,
            'tool_calls': [{'name': 'add', 'arguments': {'a': 1}, 'id': 'call_x'}],
        },
    ])
    assert converted[1] == {
        'role': 'assistant',
        'content': [{'type': 'tool_use', 'id': 'call_x', 'name': 'add', 'input': {'a': 1}}],
    }


def test_tool_results_become_user_messages_and_merge():
    """tool 결과는 role='tool'이 아니라 user의 tool_result 블록이고, 연속된 것은 한 메시지로 묶인다."""
    _, converted = _to_anthropic_messages([
        {
            'role': 'assistant', 'content': None,
            'tool_calls': [
                {'name': 'add', 'arguments': {'a': 1}, 'id': 'c1'},
                {'name': 'add', 'arguments': {'a': 2}, 'id': 'c2'},
            ],
        },
        {'role': 'tool', 'name': 'add', 'tool_call_id': 'c1', 'content': '1'},
        {'role': 'tool', 'name': 'add', 'tool_call_id': 'c2', 'content': '2'},
    ])
    assert converted[-1]['role'] == 'user'
    assert [b['tool_use_id'] for b in converted[-1]['content']] == ['c1', 'c2']


def test_missing_ids_still_round_trip():
    """fake Provider가 만든 id 없는 응답도 왕복돼야 테스트가 성립한다."""
    _, converted = _to_anthropic_messages([
        {'role': 'assistant', 'content': None, 'tool_calls': [{'name': 'add', 'arguments': {}, 'id': None}]},
        {'role': 'tool', 'name': 'add', 'tool_call_id': None, 'content': 'ok'},
    ])
    assert converted[0]['content'][0]['id'] == 'call_0'
    assert converted[1]['content'][0]['tool_use_id'] == 'call_0'


def test_tools_use_input_schema_directly():
    assert _to_anthropic_tools([AddTool()]) == [{
        'name': 'add', 'description': 'Add two integers', 'input_schema': AddTool.input_schema,
    }]
    assert _to_anthropic_tools(None) is None


def test_response_totals_usage_because_anthropic_does_not():
    """Anthropic은 total을 주지 않는다 — token_budget 집계의 전제라 여기서 만든다."""
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type='text', text='답은 '),
            SimpleNamespace(type='text', text='42'),
            SimpleNamespace(type='tool_use', name='add', input={'a': 1}, id='call_x'),
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    response = _to_model_response(message)
    assert response.text == '답은 42', '텍스트 블록이 여럿이면 이어 붙인다'
    assert response.tool_calls[0].name == 'add'
    assert response.usage == {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}


if __name__ == '__main__':
    test_system_is_lifted_out_of_messages()
    test_tool_calls_become_content_blocks()
    test_tool_results_become_user_messages_and_merge()
    test_missing_ids_still_round_trip()
    test_tools_use_input_schema_directly()
    test_response_totals_usage_because_anthropic_does_not()
    print('anthropic ok')
