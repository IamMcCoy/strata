# 5. 멀티턴

**대화 이력은 코어가 갖지 않는다.** 앱이 저장하고, 매 턴 넘겨주고, 돌려받는다.

```python
history = db.load(session_id)                        # 앱이 이미 갖고 있는 것
result = await agent.run(task, history=history)
db.save(session_id, result.metadata['messages'])     # 다음 턴에 그대로 다시 넘긴다
```

이게 전부다. `Session` 객체도, `agent.chat()`도 없다.

## 왜 코어가 안 갖나

`Agent`를 무상태로 남기기 위해서다. 상태를 코어가 들면 **여러 워커로 흩을 수 없다** —
Agent 인스턴스를 직렬화해서 큐로 보낼 수 없기 때문이다. 지금 구조에서는 워커가 각자
`Agent`를 만들고 `history`만 큐로 받으면 된다.

그리고 앱은 이미 대화를 DB에 갖고 있다. 코어가 또 갖는 것은 두 벌 관리다.

## `messages`는 순수 JSON이다

앱이 DB·큐에 넣을 대상이므로 파이썬 객체를 섞지 않는다. tool 호출도 dict다:

```python
[
  {'role': 'user', 'content': '1 더하기 2는?'},
  {'role': 'assistant', 'content': None,
   'tool_calls': [{'name': 'add', 'arguments': {'a': 1, 'b': 2}, 'id': 'call_1',
                   'provider_state': {}}]},
  {'role': 'tool', 'name': 'add', 'tool_call_id': 'call_1', 'content': '3'},
  {'role': 'assistant', 'content': '3입니다', 'tool_calls': []},
]
```

`json.dumps(result.metadata['messages'])`가 그냥 된다. Redis·Postgres·SQS 어디든 실어 나른다.

`provider_state`는 코어가 해석하지 않고 그대로 왕복시키는 주머니다. 예를 들어 Gemini 3.x는
`thought_signature`를 되돌려 받지 않으면 tool이 아예 동작하지 않는데, 그런 벤더 전용 값이
여기 담긴다. **버리지 말고 그대로 저장했다가 그대로 돌려줘라.**

## Memory와 헷갈리지 마라

| | `history` | `Memory` |
|---|---|---|
| 질문 | "아까 내가 뭐라고 했지?" | "내가 어떤 편집기 쓴다고 했더라?" |
| 내용 | 원문 그대로 | 요약된 사실 |
| 순서 | 있다 | 없다 |
| 저장 | 자동으로 쌓임 | 모델이 명시적으로 |

**대화를 Memory에 쌓지 마라.** Memory의 조회는 점수 기반이라 순서 개념이 아예 없어서
"3번째 턴에서 뭐라고 했는지"를 복원할 수 없다. 점수 함수를 아무리 잘 만들어도 마찬가지다 —
순서는 다른 자료구조가 필요한 문제다. 게다가 매 턴이 쌓이면 "네 알겠습니다" 같은 상투구가
모든 항목에 퍼져 검색 점수를 망가뜨리고, 진짜 기억이 그 사이에 묻힌다.

둘은 층을 이룬다:

```
최근 N턴   →  history (원문, 순서 보존)
    ↓ 컨텍스트가 차면 오래된 턴을 잘라냄
    ↓ 잘라내기 전에 모델이 remember로 사실만 남김
남길 사실  →  Memory (순서 무관, 영구)
```

## 대화가 길어지면

**코어는 자르지 않는다.** 받은 것을 그대로 이어붙인다. 자르는 정책이 앱마다 다르고, 토큰을
세려면 모델별 토크나이저가 필요해 의존성 0이 깨지며, 어느 턴이 중요한지는 대화를 소유한 앱이
더 잘 안다.

넘치면 프로바이더가 `400 context_length_exceeded`를 내고, `status='failed'`로 **지금까지의
답과 함께** 돌아온다. 크래시는 나지 않지만 재시도해도 영원히 안 되는 오류이므로, 폴백을
붙여뒀다면 다음 프로바이더에서도 똑같이 실패하며 비용만 쓴다.

### 순진하게 자르면 깨진다

```python
history[-20:]      # ← 이렇게 하지 마라
```

tool 왕복은 **쌍**이기 때문이다:

```python
{'role': 'assistant', 'tool_calls': [{'id': 'call_1', ...}]}   # ← 이걸 자르고
{'role': 'tool', 'tool_call_id': 'call_1', ...}                # ← 이것만 남기면 400
```

프로바이더는 `tool_call_id`가 가리키는 assistant 메시지가 없으면 요청을 거부한다.
반대(호출만 남고 결과가 없음)도 거부한다.

### `trim_history`

```python
from strata import trim_history

history = trim_history(db.load(session_id), keep_turns=10)
result = await agent.run(task, history=history)
```

턴은 `role='user'` 메시지에서 시작하고, 그 턴의 tool 왕복은 다음 user 메시지 전까지 전부
따라온다. 그래서 **턴 경계가 곧 안전한 자르는 지점**이다.

`keep_turns`가 메시지 수가 아니라 턴 수인 이유: tool을 쓰면 한 턴이 메시지 열 개가 되기도
해서 메시지 수는 예측할 수 없다. "최근 10턴"은 예측 가능하다.

**토큰은 세지 않는다.** 턴 하나가 컨텍스트를 넘길 만큼 크면 이걸로 못 막는다. 그때는 오래된
턴을 요약으로 대체하거나, 사실만 Memory로 옮기고 원문을 버려야 한다.

## 큐를 태워 여러 워커로

`messages`가 순수 JSON이므로 그대로 실어 나르면 된다:

```python
# 프로듀서
queue.push({'task_id': tid, 'task': task, 'history': db.load(session_id)})

# 워커 (다른 프로세스·다른 호스트)
job = queue.pop()
agent = Agent(provider=..., strategy=..., memory=SQLiteMemory('m.db', namespace=job['user']))
result = await agent.run(job['task'], history=job['history'])
db.save(job['task_id'], result.metadata['messages'], run_id=result.metadata['run_id'])
```

큐 자체는 코어에 두지 않는다 — `Agent`를 직렬화할 수 없어 워커가 소유해야 하고, 그러면
브로커 선택(Redis·SQS·Kafka)이 앱의 몫이 되기 때문이다.
