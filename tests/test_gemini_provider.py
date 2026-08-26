"""GeminiProvider — 메시지 변환. 실제 API 호출 없음.

OpenAI와 다른 세 지점을 고정한다: system은 config로, assistant는 role='model',
tool 호출/결과는 role이 아니라 part(function_call / function_response).
"""
from __future__ import annotations

from types import SimpleNamespace

from strata import Tool
from strata.providers.gemini import _collect
from strata.providers.gemini import _parts_of
from strata.providers.gemini import _to_gemini_contents
from strata.providers.gemini import _to_gemini_tools
from strata.providers.gemini import _usage


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers'
    input_schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}}, 'required': ['a']}

    async def execute(self, env, **kwargs):
        return kwargs['a']


def test_system_becomes_config_not_a_message():
    system, contents = _to_gemini_contents([
        {'role': 'system', 'content': '너는 조수다'},
        {'role': 'user', 'content': '안녕'},
    ])
    assert system == '너는 조수다'
    assert contents == [{'role': 'user', 'parts': [{'text': '안녕'}]}]


def test_assistant_becomes_model_role_with_function_call_parts():
    """Gemini는 'assistant'를 모른다 — 'model'이고, tool 호출은 part다."""
    _, contents = _to_gemini_contents([
        {'role': 'user', 'content': '더해줘'},
        {
            'role': 'assistant', 'content': None,
            'tool_calls': [{'name': 'add', 'arguments': {'a': 1}, 'id': 'call_x'}],
        },
    ])
    assert contents[1] == {
        'role': 'model',
        'parts': [{'function_call': {'id': 'call_x', 'name': 'add', 'args': {'a': 1}}}],
    }


def test_tool_results_become_user_parts_and_merge():
    _, contents = _to_gemini_contents([
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
    assert contents[-1]['role'] == 'user'
    assert [p['function_response']['id'] for p in contents[-1]['parts']] == ['c1', 'c2']
    # response는 dict여야 한다 — 문자열 관찰을 감싼다
    assert contents[-1]['parts'][0]['function_response']['response'] == {'result': '1'}


def test_missing_ids_still_round_trip():
    _, contents = _to_gemini_contents([
        {'role': 'assistant', 'content': None, 'tool_calls': [{'name': 'add', 'arguments': {}, 'id': None}]},
        {'role': 'tool', 'name': 'add', 'tool_call_id': None, 'content': 'ok'},
    ])
    assert contents[0]['parts'][0]['function_call']['id'] == 'call_0'
    assert contents[1]['parts'][0]['function_response']['id'] == 'call_0'


def test_tools_pass_json_schema_through_unchanged():
    """parameters_json_schema를 쓰므로 스키마 변환 코드가 필요 없다."""
    declared = _to_gemini_tools([AddTool()])
    assert declared == [{
        'function_declarations': [{
            'name': 'add', 'description': 'Add two integers',
            'parameters_json_schema': AddTool.input_schema,
        }],
    }]
    assert _to_gemini_tools(None) is None


def fake_response(parts, usage=None):
    content = SimpleNamespace(parts=parts)
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=SimpleNamespace(
            prompt_token_count=usage[0], candidates_token_count=usage[1],
            total_token_count=usage[0] + usage[1],
        ) if usage else None,
    )


def part(text=None, call=None, signature=None):
    function_call = SimpleNamespace(name=call[0], args=call[1], id=call[2]) if call else None
    return SimpleNamespace(text=text, function_call=function_call, thought_signature=signature)


def test_collect_splits_text_and_tool_calls():
    texts, calls = [], []
    _collect(
        _parts_of(
            fake_response([
                part(text='답은 '), part(text='42'), part(call=('add', {'a': 1}, 'call_x')),
            ]),
        ), texts, calls,
    )
    assert ''.join(texts) == '답은 42'
    assert calls[0].name == 'add' and calls[0].arguments == {'a': 1} and calls[0].id == 'call_x'


def test_usage_maps_to_standard_keys():
    assert _usage(fake_response([], usage=(10, 5))) == {
        'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
    }
    assert _usage(fake_response([])) == {}


def test_empty_candidates_do_not_crash():
    """안전 필터 등으로 candidates가 비어 올 수 있다 — 그때 run이 죽으면 안 된다."""
    assert _parts_of(SimpleNamespace(candidates=[])) == []
    assert _parts_of(SimpleNamespace(candidates=None)) == []


def test_thought_signature_round_trips_through_provider_state():
    """Gemini 3.x는 function_call part의 thought_signature를 돌려받지 못하면 400으로 거절한다.

    실제 API로만 드러난 계약이다. bytes라 messages(순수 JSON, ADR-0010)에 직접 못 담아
    base64로 옮겼다가 요청 조립 시점에 되돌린다.
    """
    import base64
    import json
    from dataclasses import asdict

    raw = b'\x12^\n\\\x01\x11M2'  # 실제 응답에서 오는 형태(바이너리)
    texts, calls = [], []
    _collect([part(call=('add', {'a': 1}, 'c1'), signature=raw)], texts, calls)

    assert calls[0].provider_state['thought_signature'] == base64.b64encode(raw).decode()
    dumped = json.dumps([asdict(c) for c in calls])  # 앱의 저장소를 왕복하는 지점
    restored = json.loads(dumped)

    _, contents = _to_gemini_contents([{'role': 'assistant', 'content': None, 'tool_calls': restored}])
    assert contents[0]['parts'][0]['thought_signature'] == raw, '서명이 원본 bytes로 복원돼야 한다'


def test_tool_calls_without_a_signature_still_work():
    """다른 Provider나 fake가 만든 tool_call에는 provider_state가 없다 — 그래도 깨지지 않는다."""
    _, contents = _to_gemini_contents([
        {'role': 'assistant', 'content': None, 'tool_calls': [{'name': 'add', 'arguments': {}, 'id': 'c1'}]},
    ])
    assert 'thought_signature' not in contents[0]['parts'][0]


def test_max_retries_is_translated_to_attempts():
    """Gemini는 재시도 횟수가 아니라 총 시도 횟수를 받는다 — 변환하지 않으면 벤더마다 다르게 동작한다."""
    from strata import GeminiProvider
    provider = GeminiProvider(model='gemini-2.0-flash', api_key='dummy', max_retries=2)
    assert provider.client._api_client._http_options.retry_options.attempts == 3


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
    print('gemini ok')
