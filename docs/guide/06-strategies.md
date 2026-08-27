# 6. Strategy

**실행 패턴.** 모델을 몇 번 어떤 순서로 부르고, 도구와 child agent를 어떻게 엮는지를 정한다.
`Agent`를 갈아끼우지 않고 전략만 바꾸면 실행 방식이 통째로 바뀐다.

```python
Agent(provider=..., strategy=ReActStrategy(), tools=[...])
Agent(provider=..., strategy=RLMStrategy())         # 나머지는 그대로
```

## 다섯 가지

| | 언제 | 어떻게 |
|---|---|---|
| **ReAct** | 기본. 도구를 몇 번 쓰면 답이 나오는 일 | 생각 → tool 호출 → 관찰 → 반복 → 답 |
| **Recursive** | 독립적인 하위 과제 몇 개로 쪼개지는 일 | ReAct + `spawn_agent` tool |
| **RLM** | 입력이 한 윈도우에 안 들어가는 일 | ReAct + 파이썬 REPL + `llm_query` 재귀 |
| **Reflection** | 속도보다 품질이 중요한 일 | 초안 → 비판 → 수정 (라운드 고정) |
| **Router** | 어느 패턴이 맞는지 모를 때 | 하나 고르고 그것이 끝까지 푼다 |

### ReAct

```python
ReActStrategy(prompt=None, model_params=None, description=None, **limits)
```

tool을 부르지 않고 텍스트로 답하면 루프가 끝난다. 그래서 "다 됐으면 tool 없이 답하라"가
패턴 지시에 들어 있다.

### Recursive

```python
RecursiveStrategy()
```

`spawn_agent` tool이 자동으로 붙는다. 모델이 하위 과제를 자립적인 브리프로 써서 넘기면,
child가 **깨끗한 문맥**에서 풀고 결과만 돌려준다. child는 부모의 대화를 보지 못하므로
"위에서 말한 대로"라고 쓰면 동작하지 않는다.

child도 기본적으로 같은 전략을 물려받아 다시 재귀할 수 있다. 깊이·자식 수는 한도가 막는다.

### RLM

```python
RLMStrategy()
```

거대 입력을 `Agent.run(task, context=big)`으로 넘기면 대화창이 아니라 **변수**로 들어가고,
모델은 `python` tool로만 접근한다. 조각으로 잘라 `llm_query(prompt, context=chunk)`로 여러
child에 넘기고 결과를 변수에 모은다.

```python
agent = Agent(provider=..., strategy=RLMStrategy())
result = await agent.run('이 로그에서 오류 패턴을 찾아줘', context=huge_log)
```

모델이 REPL에서 만든 변수는 다음 턴의 지시에 목록으로 나타난다. `llm_query`도 그 REPL에
주입돼 있다.

> ⚠️ `python` tool은 샌드박스가 아니다. 신뢰된 환경 전용이며, 격리가 필요하면 같은
> `name='python'`으로 컨테이너 구현을 만들어 `tools=`에 등록하면 그쪽이 쓰인다.

### Reflection

```python
ReflectionStrategy(rounds=2, worker=None, critic_prompt=..., description=None)
```

초안·비판·수정을 **전부 child agent로** 띄운다. 비판자가 초안을 쓴 대화를 보지 못하는 것이
핵심이다 — 자기 초안에 물든 문맥 안에서 하는 비판은 비판이 아니다.

라운드는 고정이고 조기 종료가 없다. 비판자에게 "이제 충분한가"를 묻는 순간 모델이 스스로
만족했는지 판단하게 되고, 그걸 막는 것이 이 패턴의 존재 이유다. 끄려면 `rounds=0`.

```python
result = await agent.run('회사 소개 문단을 써줘')
result.result                    # 최종본
result.evidence                  # [{'critique': ..., 'draft': ...}, ...] 라운드별 기록
result.metadata['rounds_completed']
```

`worker=`로 초안·수정을 맡는 전략을 갈아끼운다 — `worker=RecursiveStrategy()`면 초안 자체가
재귀로 만들어진다.

### Router

```python
RouterStrategy(routes, *, default, context_route='rlm', prompt=None, description=None)
```

```python
agent = Agent(provider=..., strategy=RouterStrategy({
    'react':      ReActStrategy(),
    'recursive':  RecursiveStrategy(),
    'rlm':        RLMStrategy(),
    'reflection': ReflectionStrategy(),
}, default='react'))
```

두 단계로 고른다:

1. **결정적 규칙이 먼저** — `run(task, context=...)`로 거대 입력이 왔으면 묻지 않고
   `context_route`(기본 `'rlm'`)로 간다. "한 윈도우에 안 들어간다"는 사실이지 판단이 아니라서,
   모델에게 물으면 토큰만 쓰고 틀릴 기회만 준다. 이 경우 모델 호출은 **0회**다.
2. **아니면 tool call 1회** — `route(strategy: enum[...])`를 광고해 한 번 부르고
   고른 이름을 읽는다. enum이라 고를 수 있는 값이 스키마로 고정되고, 형식을 못 지키면
   `default`로 떨어진다.

**고른 전략을 같은 Context에서 그대로 실행한다.** child로 띄우면 child가 대화 이력을 못 봐서
라우터를 씌우는 순간 멀티턴이 깨지기 때문이다. 어느 전략이 골라졌는지는 결과에 남는다:

```python
result.metadata['route']      # 'reflection'
```

`default`는 필수 인자다. 라우팅 실패는 곧 전체 실패이므로(어느 전략도 못 고른다) 기본값을
빠뜨릴 수 없게 했다.

## 판단 근거를 손보기 — 가장 값싼 튜닝

라우터는 각 전략의 `description`을 모아 분류 프롬프트를 만든다. 기본값은 영어 일반론이라
당신의 도메인에 맞지 않는다. **도메인 용어로 다시 쓰면 모델도 프롬프트도 안 건드리고
정확도가 올라간다:**

```python
RouterStrategy({
    'lookup': ReActStrategy(description='단순 조회·계산. 사내 API로 바로 답할 수 있는 질문.'),
    'bulk':   RLMStrategy(description='대용량 로그·문서 일괄 처리.'),
    'report': ReflectionStrategy(description='고객에게 나가는 문서. 초안을 다듬어야 하는 일.'),
}, default='lookup')
```

`description`이 비어 있으면 클래스 이름으로 대신하므로, 커스텀 전략도 아무것도 안 해도
라우팅에 낀다.

## 패턴 지시 바꾸기

각 전략은 모델에게 보내는 고정 지시(harness prompt)를 갖는다. system은 이렇게 조립된다:

```
당신의 instructions  +  전략의 prompt  +  전략의 현재 상태(environment)
```

```python
ReActStrategy(prompt='...나만의 규칙...')     # 통째로 교체
ReActStrategy(prompt='')                      # 끄기
```

내보내진 상수를 이어 붙일 수도 있다 — `REACT_PROMPT`, `RECURSIVE_PROMPT`, `RLM_PROMPT`,
`ROUTER_PROMPT`, `REFLECTION_CRITIC_PROMPT`. **내보낸 상수가 곧 모델이 보는 텍스트**다.

```python
from strata import REACT_PROMPT
ReActStrategy(prompt=REACT_PROMPT + '\n\n답은 항상 한국어로.')
```

## 커스텀 전략

```python
from strata import Strategy, AgentResult


class TwoPass(Strategy):
    description = '먼저 계획을 세우고, 그 계획대로 실행한다.'

    async def execute(self, context, runtime) -> AgentResult:
        plan = await runtime.generate(context, instructions='먼저 계획만 세워라.')
        context.messages.append({'role': 'assistant', 'content': plan.text})
        final = await runtime.generate(context, instructions='이제 계획대로 실행해라.')
        return AgentResult(result=final.text)
```

지켜야 할 것은 하나다: **리소스에는 `runtime`을 통해서만 닿는다.**

```python
await runtime.generate(context, tools=..., instructions=...)     # 모델
await runtime.execute_tool(name, arguments, context)             # tool
await runtime.spawn_agent(task, context, strategy=..., context=...)  # child agent
runtime.memory                                                    # Memory
runtime.execution                                                 # 실행 트리
```

`runtime.provider.generate()`를 직접 부르면 한도 검사·토큰 집계·경고가 전부 건너뛰어진다.
`Agent()`를 직접 만들어 child로 쓰면 그 실행은 한도 밖에서 돌고 트리에도 안 남는다.

**한도를 몰라도 막힌다.** `runtime.generate`를 무한히 부르면 `max_iterations`에 걸려
`budget_exceeded`로 끝난다. 커스텀 전략이 별도로 방어할 필요가 없다.
