# 1. Agent

`Agent`는 **조합 단위**다. 어떻게 실행할지(패턴)는 `Strategy`가, 무엇으로 실행할지(모델·도구·기억)는
당신이 넘긴 객체들이 정한다. Agent 자신은 실행 로직을 갖지 않는다.

```python
Agent(
    provider,                 # 필수 — 모델
    strategy,                 # 필수 — 실행 패턴
    tools=None,               # list[Tool]
    memory=None,              # Memory 구현
    instructions=None,        # str — system 지시
    config=None,              # RuntimeConfig — 실행 한도
    on_delta=None,            # (text, execution_id) -> None. 주면 스트리밍이 켜진다
)
```

`instructions`가 messages와 분리돼 있는 이유: 전략이 자기 패턴 지시를 뒤에 덧붙여야 하고,
child agent가 이 지시를 물려받아야 하기 때문이다. 대화에 섞어두면 둘 다 못 한다.

## 진입점은 `run` 하나다

```python
result = await agent.run(
    task,              # 이번에 시킬 일
    context=None,      # 거대 입력
    history=None,      # 이전 턴들의 messages
)
```

`stream()` 같은 두 번째 메서드는 없다. 스트리밍은 `on_delta` 콜백이고, 콜백을 줘도
`run`의 반환은 여전히 완결된 결과다. 그래서 스트리밍을 켜고 끄더라도 나머지 코드가 그대로다.

`context`는 **messages에 들어가지 않는다.** 100MB 로그를 넘겨도 대화창에 인라인되지 않고
변수로 보관되며, 모델은 그것을 파이썬 코드로만 다룬다(→ [6. Strategy](06-strategies.md)의 RLM).
`Agent.run(task, context=big)`은 "이건 한 번에 읽을 수 없는 입력이다"라는 선언이다.

## 돌아오는 것 — `AgentResult`

```python
result.status      # 'completed' | 'failed' | 'budget_exceeded' | 'cancelled'
result.result      # 최종 텍스트
result.evidence    # 근거 목록 (Reflection이 라운드별 비판·초안을 넣는다)
result.metadata    # 부가 정보
```

`metadata`에 늘 들어 있는 것:

| 키 | |
|---|---|
| `messages` | 이번 run의 전체 transcript. 다음 턴에 `history=`로 그대로 돌려준다 |
| `run_id` | UUIDv7. 로그와 실행 트리를 가리키는 이름. 앱의 task_id 옆에 적어둔다 |
| `route` | 라우터를 쓴 경우 어느 전략이 골라졌는지 |
| `reason` | 실패·한도 초과의 원인 (`max_depth`, `timeout`, `provider_error` 등) |

## 실패는 예외가 아니라 결과다

한도를 넘겼거나 모델 API가 죽었을 때 예외를 던지지 않는다. 그렇게 하면 **그때까지 쓴 토큰이
통째로 버려지기** 때문이다. 대신 상태로 돌아오고, `result.result`에는 지금까지의 답이 담긴다.

```python
result = await agent.run(task)

if result.status != 'completed':
    logger.warning('run=%s %s (%s)', result.metadata['run_id'],
                   result.status, result.metadata.get('reason'))
# 그래도 result.result 를 쓸 수 있다 — 부분 답이 들어 있다
```

| status | 언제 |
|---|---|
| `completed` | 정상 |
| `budget_exceeded` | `max_depth`·`max_iterations`·`max_children`·`token_budget`·`timeout` 초과 |
| `failed` | 모델 API 오류(재시도 소진), 또는 child agent가 던진 예외 |
| `cancelled` | `runtime.cancel()`로 협조적 취소 |

**당신 코드의 버그는 그대로 전파된다.** 오타·타입 오류를 `status='failed'`로 삼켜버리면
디버깅이 불가능해진다. 삼키는 것은 "인프라 오류"뿐이다.

## 실행 기록

```python
agent.runtime.usage                # 이번 run 전체 토큰
agent.runtime.execution.root       # 실행 트리 루트
```

`ExecutionNode` 하나가 agent 하나다:

```python
node.task           # 무엇을 시켰나
node.depth          # 재귀 깊이
node.status         # 결과
node.iterations     # 모델을 몇 번 불렀나
node.usage          # 이 노드가 직접 쓴 토큰
node.children       # 이 노드가 띄운 child들
node.subtree_usage()  # 자신 + 모든 자손의 토큰 — "어느 가지가 비쌌나"의 유일한 답
```

트리 전체를 찍어보는 코드:

```python
def render(node, indent=0):
    print('  ' * indent + f'[{node.status}] {node.task[:40]} → {node.subtree_usage()["total_tokens"]} tokens')
    for child in node.children:
        render(child, indent + 1)

render(agent.runtime.execution.root)
```

`agent.runtime`은 **마지막 run**의 것이다. run마다 Runtime이 새로 만들어지고, 그 run이 띄운
child agent들이 같은 Runtime을 공유한다. 그래서 `Agent` 인스턴스는 상태가 없고 여러 워커에서
그대로 재사용할 수 있다.

## 로깅

라이브러리는 로그를 설정하지 않는다. 켜는 것은 앱의 몫이다:

```python
import logging
logging.basicConfig(level=logging.INFO)      # agent.started / agent.finished
logging.getLogger('strata').setLevel(logging.DEBUG)   # + provider.request / agent.spawned / tool 실행
```

모든 줄에 `run=`과 `exec=`가 붙어 있어 한 실행을 골라낼 수 있다.
