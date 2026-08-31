# 3. Tool

모델이 바깥 세상에 닿는 유일한 통로. **구현할 것은 `execute` 하나**다.

```python
from strata.tools import Tool


class SearchTool(Tool):
    name = 'search'                                   # 모델이 부를 이름
    description = 'Search the internal wiki'          # 언제 쓰는지 한 줄 — 모델이 읽는다
    input_schema = {                                  # JSON Schema
        'type': 'object',
        'properties': {
            'query': {'type': 'string', 'description': 'What to search for'},
            'limit': {'type': 'integer', 'description': 'Max results'},
        },
        'required': ['query'],
    }

    async def execute(self, env, query='', limit=5, **kwargs):
        rows = await db.search(query, limit)
        return [{'title': r.title, 'url': r.url} for r in rows]
```

```python
agent = Agent(provider=..., strategy=ReActStrategy(), tools=[SearchTool()])
```

## 반환값

문자열이면 그대로, 나머지는 JSON으로 직렬화되어 모델에게 관찰(observation)로 간다.
**모델이 읽을 것**이라는 걸 잊지 마라 — 거대한 덤프를 돌려주면 컨텍스트만 태운다.

```python
return f'{len(rows)}건. 상위 3건: ...'     # 좋음
return rows                                # 10,000행이면 나쁨
```

## `env` — Runtime에 닿는 유일한 길

대부분의 Tool은 무시한다. 필요한 경우에만 쓴다.

```python
async def execute(self, env, **kwargs):
    env.context.variables['count'] = 1      # 이 실행의 상태
    env.context.metadata['task']            # 원래 시킨 일
    env.runtime.memory                      # Memory 구현
    result = await env.runtime.spawn_agent(  # child agent 띄우기
        '이 조각만 요약해라', env.context, context=chunk,
    )
```

**child agent를 만들려면 반드시 `env.runtime.spawn_agent()`를 거친다.** 깊이·자식 수 한도
검사, 실행 트리 등록, 토큰 집계가 전부 이 지점에 걸려 있다. 직접 `Agent()`를 만들어 실행하면
그 실행은 한도 밖에서 돌고 트리에도 안 남는다.

## 예외는 관찰이 된다

Tool이 던진 예외는 실행을 죽이지 않고 모델에게 문자열로 전달된다:

```
Tool 'search' failed: ConnectionError('timed out')
```

모델은 이걸 읽고 인자를 고치거나 다른 방법을 찾는다. **run은 모델의 실수로 죽지 않는다.**
없는 tool을 부르면 사용 가능한 목록이 함께 온다.

그러니 Tool 안에서 방어적으로 `try/except`를 두를 필요가 없다. 다만 **던지는 예외 메시지가
모델에게 유용해야** 한다:

```python
raise ValueError('query must not be empty')          # 좋음 — 모델이 고칠 수 있다
raise ValueError('e')                                 # 나쁨
```

## 내장 tool 세 가지

```python
from strata.tools import MemoryTool, SpawnAgentTool, PythonTool
```

| | 이름 | 하는 일 |
|---|---|---|
| `MemoryTool` | `remember` | 다음 실행에 남길 사실을 모델이 명시적으로 저장 |
| `SpawnAgentTool` | `spawn_agent` | 하위 과제를 새 문맥의 child agent에 위임 |
| `PythonTool` | `python` | 상태가 유지되는 파이썬 REPL. `llm_query`가 주입된다 |

`SpawnAgentTool`과 `PythonTool`은 각각 `RecursiveStrategy`·`RLMStrategy`가 **자동으로**
달아준다. 직접 `tools=`에 넣을 필요는 없다.

> ⚠️ **`PythonTool`은 샌드박스가 아니다.** 모델이 만든 코드가 이 프로세스 권한으로 실행된다 —
> 파일·네트워크·환경변수 전부. **신뢰된 환경 전용**이다. 최종 사용자 입력이 프롬프트에
> 닿는다면 아래 "교체하기"를 읽어라.

## 교체하기 — 같은 이름이 이긴다

전략이 기본으로 다는 tool과 **같은 `name`**을 `tools=`에 넣으면 당신 것이 쓰인다.
샌드박스가 그 통로다:

```python
class SandboxedPython(Tool):
    name = 'python'                      # PythonTool과 같은 이름 → 이쪽이 이긴다
    description = 'Execute Python code in an isolated container'
    input_schema = {'type': 'object', 'properties': {'code': {'type': 'string'}},
                    'required': ['code']}

    async def execute(self, env, code='', **kwargs):
        return await my_container.run(code)


agent = Agent(provider=..., strategy=RLMStrategy(), tools=[SandboxedPython()])
```

코어가 인프로세스 샌드박스를 제공하지 않는 이유: CPython에서 인프로세스 격리는 우회
가능하다는 것이 정설이고(객체 그래프·예외 객체·프레임 등으로 탈출 경로가 계속 발견된다),
**부분적 방어는 안전하다는 착각을 만들어 아무것도 없는 것보다 위험하다.** 없으면 신뢰된
입력만 넣지만, 있으면 신뢰되지 않은 입력을 넣는다.

격리 구현이 풀어야 할 숙제가 하나 있다: `llm_query`가 프로세스·컨테이너 경계를 넘어
호스트로 콜백해야 한다. 코어는 `env.runtime.spawn_agent()`를 주고, 그 위의 RPC는 구현의 몫이다.
