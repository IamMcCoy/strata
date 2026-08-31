"""AnthropicProvider — 메시지 변환. 실제 API 호출 없음.

OpenAI와 근본적으로 다른 세 지점을 고정한다: system은 최상위 파라미터,
tool 호출/결과는 content block, tool 결과는 role='user'.
"""
from __future__ import annotations

from types import SimpleNamespace

from strata.providers.anthropic import _to_anthropic_messages
from strata.providers.anthropic import _to_anthropic_tools
from strata.providers.anthropic import _to_model_response
from strata.tools import Tool


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


def test_max_retries_reaches_the_client():
    """OpenAIProvider와 같은 이름·같은 기본값이어야 갈아끼울 때 놀라지 않는다."""
    from strata.providers import AnthropicProvider
    assert AnthropicProvider(api_key='k').client.max_retries == 2
    assert AnthropicProvider(api_key='k', max_retries=5).client.max_retries == 5


if __name__ == '__main__':
    test_system_is_lifted_out_of_messages()
    test_tool_calls_become_content_blocks()
    test_tool_results_become_user_messages_and_merge()
    test_missing_ids_still_round_trip()
    test_tools_use_input_schema_directly()
    test_response_totals_usage_because_anthropic_does_not()
    test_max_retries_reaches_the_client()
    print('anthropic ok')


def test_thinking_blocks_become_reasoning_not_answer_text():
    """thinking은 text와 다른 블록 타입이다 — 안 꺼내면 그냥 버려지고, text에 섞으면 답이 오염된다.

    스트리밍 경로도 같은 함수를 쓴다(SDK stream 헬퍼의 get_final_message → _to_model_response).
    text_stream은 text 블록만 흘리므로 사고가 on_delta로 새지 않는다.
    """
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type='thinking', thinking='17*23 = 17*20 + 17*3'),
            SimpleNamespace(type='text', text='391'),
        ],
        usage=None,
    )
    response = _to_model_response(message)
    assert response.text == '391'
    assert response.reasoning == '17*23 = 17*20 + 17*3'
