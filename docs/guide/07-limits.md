# 7. 한도·취소·관찰

에이전트는 재귀하고 반복한다. 막지 않으면 **비용이 지수로 튄다.** 그 배관이 여기 있다.

## 한도는 Runtime이 강제한다

```python
from strata.agent import Agent
from strata.runtime import RuntimeConfig

agent = Agent(provider=..., strategy=..., config=RuntimeConfig(
    max_depth=5,          # 재귀 깊이
    max_iterations=30,    # agent 하나가 모델을 부를 수 있는 횟수
    max_children=8,       # agent 하나가 띄울 수 있는 child 수
    token_budget=None,    # run 전체 토큰 상한
    timeout=None,         # 초 단위, run 전체
))
```

**전략이 한도를 몰라도 걸린다.** 검사가 전략이 아니라 `runtime.generate`와
`runtime.spawn_agent` 안에 있기 때문이다. 남이 만든 커스텀 전략을 가져다 써도 안전하다.

초과하면 **예외가 아니라 결과**로 돌아온다:

```python
result = await agent.run(task)
if result.status == 'budget_exceeded':
    print(result.metadata['reason'])   # 'max_depth' | 'max_iterations' | 'max_children'
                                       # | 'token_budget' | 'timeout'
    print(result.metadata['limit'])    # 걸린 값
    print(result.result)               # 지금까지의 답 — 버려지지 않는다
```

예외로 만들면 그때까지 쓴 토큰이 통째로 날아간다. 부분 답이 아무것도 없는 것보다 낫다.

재귀 중에 `max_depth`·`max_children`에 걸리면 부모 모델이 관찰로 그 사실을 받는다:

```
{'status': 'budget_exceeded', 'metadata': {'reason': 'max_children', 'limit': 8}}
```

모델은 "더 위임하지 말고 지금 있는 걸로 답하라"는 신호로 읽는다. 실행이 죽지 않는다.

## 전략이 한도를 제안할 수 있다

어떤 한도의 적정값은 전략만 안다. `ReflectionStrategy(rounds=4)`는 구조적으로 child가
`1 + 4*2 = 9`개 필요한데, 기본 `max_children=8`이면 조용히 잘린다. 그래서 전략이 제안한다:

```python
ReflectionStrategy(rounds=4)              # max_children을 9로 올려달라고 제안
ReActStrategy(max_iterations=10)          # 전략 옆에서 루프 상한을 준다
RecursiveStrategy(max_depth=2, max_children=3)
```

우선순위는 하나뿐이다:

```
당신이 RuntimeConfig에 명시한 값  >  전략의 제안  >  기본값
```

```python
Agent(strategy=ReflectionStrategy(rounds=4))                         # max_children 8 → 9
Agent(strategy=ReflectionStrategy(rounds=4),
      config=RuntimeConfig(max_children=3))                          # 3. 당신이 이긴다
```

**강제는 여전히 Runtime이다.** 제안은 값의 출처만 바꾼다. 그리고 전략에서 파생된 한도는
**하한으로만** 쓰인다 — 올리기만 하고 내리지 않는다. 한도는 run 전체가 공유하므로,
`rounds=2`가 필요한 5개에 맞춰 내리면 안에서 도는 다른 전략의 여유까지 깎이기 때문이다.

이름을 틀리면 **생성 시점에** 잡힌다:

```python
ReActStrategy(max_iteration=10)
# TypeError: unknown limit(s) ['max_iteration']; known: ['max_children', 'max_depth', ...]
```

## 취소

두 종류이고 결말이 다르다.

**협조적 취소** — 지금까지의 답을 살린다:

```python
task = asyncio.create_task(agent.run(long_job))
...
agent.runtime.cancel('사용자가 중단')      # 새 모델 호출·child 생성을 막는다
result = await task
result.status                              # 'cancelled'
result.result                              # 지금까지의 답
result.metadata['reason']                  # '사용자가 중단'
```

이미 쓴 토큰이 버려지지 않으므로 **사용자가 누르는 정지 버튼은 이쪽**이다.

**하드 취소** — `asyncio.CancelledError`. 그대로 전파되지만 실행 트리에는 `cancelled`로
남는다. 진행 중이던 tool은 끝까지 간다(취소가 최대 tool 하나만큼 늦는다).

## 관찰

### 토큰 — 두 층

```python
agent.runtime.usage                        # run 전체 합계
agent.runtime.execution.root.usage         # 루트 노드가 직접 쓴 것
node.subtree_usage()                       # 그 가지 전체 — 재귀에서 유일하게 의미 있는 값
```

재귀에서 "어느 갈래가 비쌌나"는 노드별로만 알 수 있다. 총합만 보면 원인을 못 찾는다.

### 실행 트리

```python
def render(node, indent=0):
    cost = node.subtree_usage()['total_tokens']
    print('  ' * indent + f'[{node.status}] d{node.depth} {node.task[:40]!r} · {cost} tokens')
    for child in node.children:
        render(child, indent + 1)

render(agent.runtime.execution.root)
```

```
[completed] d0 '보고서 작성' · 12,430 tokens
  [completed] d1 '오픈소스 조사' · 5,120 tokens
    [completed] d2 'RLM 계열 심층' · 2,050 tokens
  [budget_exceeded] d1 '상용 조사' · 1,900 tokens
```

### 로그

라이브러리는 로그를 설정하지 않는다 — 켜는 것은 앱의 몫이다:

```python
import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('strata').setLevel(logging.DEBUG)
```

| 레벨 | 나오는 것 |
|---|---|
| INFO | `agent.started` / `agent.finished` / `router.selected` |
| DEBUG | `provider.request` / `provider.response` / `agent.spawned` / `agent.completed` / `memory.retrieve` |
| WARNING | `provider.error` / `model.tool_call_may_have_leaked_as_text` |

모든 줄에 `run=`과 `exec=`가 붙어 한 실행을 골라낼 수 있다:

```
run=01a041a3-1e5e-7a58-… exec=exec_0 agent.started task=보고서 작성
run=01a041a3-1e5e-7a58-… exec=exec_1 agent.spawned parent=exec_0 depth=1 task=오픈소스 조사
```

`run_id`는 코어가 발급한다(UUIDv7 — 시간순 정렬이 된다). `exec_0`은 run마다 재사용되므로
그것만으로는 프로세스·run을 넘는 기록이 뒤섞인다. 앱은 자기 task_id 옆에 `run_id`를 적어둔다:

```python
db.save(task_id, run_id=result.metadata['run_id'])
```

### 알아둘 경고 하나

```
WARNING model.tool_call_may_have_leaked_as_text names=['add'] text=<|tool_call>call:add{...}
```

모델이 tool call 형식을 못 지켜 벤더 고유 문법이 **본문 텍스트로 샜다**는 뜻이다. tool 호출이
비어 있으므로 프레임워크는 그것을 "최종 답"으로 보고 루프를 끝낸다 — 쓰레기가 정답이 된다.

작은 모델이나 tool 파서 설정이 안 된 서버에서 일어난다. 이 경고가 보이면 모델을 키우거나
서버의 tool 파서 설정을 확인하라. 동작은 바꾸지 않는다(오탐이 가능하기 때문).

## 비용을 줄이는 순서

1. **한도부터 건다.** `token_budget`과 `timeout`은 사고를 막는 마지막 방어선이다.
2. **분류·요약 같은 잔일은 싼 모델로.** 라우터의 `classify()`를 오버라이드하면 분류만
   다른 프로바이더로 돌릴 수 있다.
3. **`subtree_usage()`로 비싼 가지를 찾는다.** 대개 재귀 하나가 전체 비용의 대부분이다.
4. **거대 입력은 messages에 넣지 마라.** `context=`로 넘기면 대화창을 태우지 않는다.
