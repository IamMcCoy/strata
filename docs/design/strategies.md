# Strategies

Strategy는 Agent가 문제를 해결하는 **실행 패턴**을 정의한다.
**프레임워크의 핵심 확장 포인트**다. ([ADR-0003](../adr/0003-strategy-as-first-class-abstraction.md))

```python
class Strategy(ABC):

    async def execute(
        self,
        context,
        runtime,
    ) -> AgentResult:
        ...
```

Strategy는 Provider·Tool·Memory·Child Agent에 직접 접근하지 않고
**Runtime이 제공하는 primitive를 통해** 접근한다
([ADR-0008](../adr/0008-all-primitives-through-runtime.md)):

```python
runtime.generate(context, tools=..., instructions=...)   # LLM 호출 (system 조립·한도·usage)
runtime.execute_tool(name, arguments, context, tools=...)  # Tool 실행 (예외 → 관찰)
runtime.spawn_agent(task, parent_context, context=...)   # Child Agent (한도 → 계약)
runtime.memory
runtime.execution
```

`runtime.provider`를 직접 호출하지 않는다 — 한도·집계·이벤트가 `generate`에 걸려 있다.

구현: `ReActStrategy`, `RecursiveStrategy`, `RLMStrategy`, `ReflectionStrategy`, `RouterStrategy`.
향후: `PlanExecuteStrategy`,
`DebateStrategy`, `SelfConsistencyStrategy`, `MultiAgentStrategy`, `CustomStrategy`.
각 패턴의 배경과 Strata primitive 매핑은
[agentic-patterns-background.md](../overview/agentic-patterns-background.md) 참조.

## 파라미터 — 한도(limit)와 knob

전략에 붙는 값은 두 종류이고 소유자가 다르다. 섞으면 안전 속성이 깨진다.

전략에 붙는 값은 두 종류다. **둘 다 생성자에서 받지만 소유자가 다르다**
([ADR-0014](../adr/0014-strategy-proposes-limits.md)).

|  | **한도(limit)** | **패턴 knob** |
| --- | --- | --- |
| 목적 | 폭주·비용 폭발 방지 | 그 패턴의 동작 정의 |
| 값을 제안 | `Strategy.limits` (전략만 아는 공식이 있을 때) | `Strategy.__init__` 인자 |
| **강제** | **Runtime** — 전략이 몰라도 걸린다 | 없음 |
| 초과하면 | `budget_exceeded` 계약 반환 | "초과"라는 개념이 없다 |
| 최종 결정 | 사용자 `RuntimeConfig` > `Strategy.limits` > 기본값 | 생성자 인자 그대로 |

```python
Agent(provider=p, strategy=ReflectionStrategy(rounds=4))       # child 9개가 필요함을 전략이 안다
Agent(provider=p, strategy=ReActStrategy(max_iterations=10))   # 루프 상한을 전략 옆에서 준다
Agent(provider=p, strategy=ReflectionStrategy(rounds=4),
      config=RuntimeConfig(max_children=3))                    # 사용자가 명시하면 언제나 사용자가 이긴다
```

| Strategy | 실질적으로 걸리는 한도 | 스스로 제안하는 값 | knob |
| --- | --- | --- | --- |
| ReAct | `max_iterations`, `token_budget`, `timeout` | (없음) | `prompt`, `model_params` |
| Recursive | + `max_depth`, `max_children` | (없음) | (상속) |
| RLM | + `max_depth`, `max_children` | (없음) | (상속) |
| Reflection | **`max_children`** (아래 참조) | `max_children ≥ 1 + rounds*2` (하한, 올리기만) | `rounds`, `worker`, `critic_prompt` |

한도를 Strategy로 **옮기지는** 않는다. `max_iterations`는 "ReAct의 루프 상한"이 아니라
**노드당 `generate` 호출 상한**이고, 강제를 전략으로 옮기면 Custom Strategy가 `runtime.generate`를
무한히 부를 수 있게 되어 "한도를 몰라도 Runtime이 막아 준다"는 확장점의 안전 속성이 사라진다.
바뀐 것은 *누가 기본값을 제안하는가*뿐이다.

`rounds`는 반대 방향이다 — `RuntimeConfig`에 넣지 않는다. 2라운드를 도는 것은 폭주가 아니라
Reflection의 정의이고, 넣는 순간 Reflection을 쓰지 않는 사용자도 보는 설정이 된다.
대신 rounds에서 파생되는 **한도**(`max_children`)를 전략이 계산해 제안한다.

**파생된 한도는 하한이다 — 올리기만 하고 내리지 않는다.** 한도는 run 전체가 공유하므로,
`rounds=2`가 필요한 child 5개에 맞춰 `max_children`을 8에서 내리면 `worker`가 재귀 위임에
쓸 자식 수까지 같이 조여진다. 모자랄 때만 올린다.

## 지시(instructions)와 Context

system 지시는 `Context.instructions`에 messages와 **분리**해 둔다. 이유:

- Strategy가 호출 시점에 덧붙일 수 있다 — `generate(context, instructions=...)` 로 이번
  호출의 system만 바꾼다(RLM이 변수 환경 설명을 붙이는 방식). 원본은 오염되지 않는다.
- child가 상속한다 — `spawn_agent(instructions=None)`이면 parent의 **원본** 지시를 물려받고,
  child의 Strategy가 자기 환경 설명을 다시 덧붙인다.

`Agent(instructions=...)` → root Context, `spawn_agent(instructions=...)` → child Context.

system 메시지는 **두 층**으로 조립된다 — `ReActStrategy.instructions()` 한 곳에서:

```text
system = Context.instructions   (사용자 지시 — "무엇을". 원본·child 상속)
       + Strategy.prompt        (패턴 지시 — "어떻게 움직여라". 고정 텍스트, harness prompt)
       + environment(context)   (현재 상태 — RLM의 변수 목록. 호출마다 갱신, 기본 없음)
```

- `prompt`는 Strategy **클래스 속성**이고 **고정 텍스트**다(템플릿 아님 — `.format()` 없음).
  `REACT_PROMPT` / `RECURSIVE_PROMPT` / `RLM_PROMPT`(각 전략 모듈 상단, `strata`에서 export)를
  기본값으로 갖고, 하위 전략은 모듈 레벨 문자열 concat(`RECURSIVE_PROMPT = REACT_PROMPT + ...`)으로
  공통 규칙 위에 자기 규칙을 얹는다 — `RecursiveStrategy.prompt`를 출력하면 그게 모델이 보는 전부다.
- 덮어쓰기 세 단계: `ReActStrategy(prompt='...')` 인자 → 서브클래스 `prompt = ...` →
  `instructions()` 오버라이드. `prompt=''`이면 패턴 지시를 끈다.
- `environment(context)`는 실행 중 바뀌는 설명을 붙이는 훅이다. RLM이 `context.variables` 목록을,
  향후 Reflection이 "이전 초안"을, Plan-Execute가 "현재 계획"을 붙이는 자리 — 변하는 것은 prompt에
  구멍을 뚫지 말고 여기로.
- 각 prompt가 규정하는 것(harness engineering): ReAct = tool 사용 규율·오류 관찰 회복·**종료 규약**
  (최종 답은 tool call 없이 텍스트)·부분 답 우선. Recursive = child 격리(대화를 못 본다 → 자기완결
  task)·위임 기준·`failed`/`budget_exceeded` 관찰 처리·종합. RLM = 변수 환경·창 보호(통째 print 금지)·
  `llm_query` 자기완결+반환 형식·청킹·검증·traceback 회복.

## ReAct Strategy

Tool을 반복적으로 사용하며 문제를 해결하는 패턴.

```text
Task → LLM → Action → Tool → Observation → LLM → ... → Final Answer
```

```python
class ReActStrategy(Strategy):
    default_tools: tuple[Tool, ...] = ()             # 전략 기본 tool — 하위 전략이 선언. registry와 이름 충돌 시 registry 우선
    prompt: str = REACT_PROMPT                       # 패턴 지시(고정 텍스트) — 하위 전략이 교체, 사용자가 prompt= 로 덮어씀

    def __init__(self, *, prompt=None, model_params=None):
        if prompt is not None:
            self.prompt = prompt
        self.model_params = dict(model_params or {})  # 이 전략의 모든 generate에 실리는 샘플링 파라미터

    def tools(self, runtime) -> list[Tool]:          # 광고할 tool = registry 전체 + default_tools
        return [*runtime.tools.values(), *(t for t in self.default_tools if t.name not in runtime.tools)]

    def environment(self, context) -> str | None:    # 호출 시점에 변하는 상태 설명 — 하위 전략 확장 지점
        return None

    def instructions(self, context, runtime):        # system = 사용자 지시 + 패턴 지시 + 현재 상태
        parts = (context.instructions, self.prompt, self.environment(context))
        return '\n\n'.join(p for p in parts if p) or None

    async def execute(self, context, runtime):
        tools = self.tools(runtime)
        by_name = {t.name: t for t in tools}
        while True:                                   # 상한은 runtime.generate가 강제
            response = await runtime.generate(context, tools=tools,
                                              instructions=self.instructions(context, runtime),
                                              **self.model_params)
            context.messages.append({'role': 'assistant', 'content': response.text,
                                     'tool_calls': response.tool_calls})
            if not response.tool_calls:
                return AgentResult(result=response.text)
            for call in response.tool_calls:
                observation = await runtime.execute_tool(call.name, call.arguments, context, tools=by_name)
                context.messages.append({'role': 'tool', 'name': call.name,
                                         'tool_call_id': call.id, 'content': _observation_text(observation)})
```

- "Thought"는 네이티브 tool calling 모델의 `response.text`에 암묵적으로 담긴다 — 별도의
  Thought/Action 파싱 프롬프트를 쓰지 않는다. tool call의 Provider별 형식 차이는
  `ModelResponse.tool_calls`(`ToolCall`)가 흡수한다 ([abstractions.md](abstractions.md#provider)).
- 루프에 `max_iterations` 검사가 **없다**. `runtime.generate`가 노드당 호출 수를 세고
  초과 시 `BudgetExceeded`를 올리며, Runtime이 `budget_exceeded` 계약(마지막 assistant
  텍스트 포함)으로 변환한다 ([runtime.md](runtime.md#execution-control)).
- 관찰은 문자열이면 그대로, 아니면 JSON(`_observation_text`). Tool 예외·unknown tool도
  관찰로 돌아와 모델이 회복한다.
- tool call은 순차 실행이다. 병렬 child가 필요한 패턴(Debate 등)은 `asyncio.gather`로 바꾼다.
- `default_tools`는 하위 전략이 "이 패턴에 필요한 tool"을 선언하는 자리다. 사용자가 registry에
  같은 이름의 Tool을 등록하면 그것이 광고된다 — 샌드박스 python, 근거를 남기는 spawn 등 교체점.

## Recursive Strategy — 위임형 재귀

Agent가 문제 해결 과정에서 새로운 Agent Execution을 생성한다.

```text
Root Agent
    ├── Tool
    ├── Tool
    └── Child Agent
            ├── Tool
            └── Child Agent
                    └── ...
```

```python
class RecursiveStrategy(ReActStrategy):
    default_tools = (SpawnAgentTool(),)
    prompt = RECURSIVE_PROMPT                        # = REACT_PROMPT + 위임 규칙
```

그게 전부다. **트리거는 Tool, 메커니즘은 Runtime** ([ADR-0007](../adr/0007-spawn-trigger-is-a-tool.md)):
`SpawnAgentTool.execute(env, task, context=None)`이 `env.runtime.spawn_agent(task, env.context,
context=context)`를 부르고 결과 계약(`{status, result}`)을 관찰로 돌려준다. 한도 초과 시 모델은
`budget_exceeded` 관찰을 받고 스스로 답해야 한다. registry에 등록되지 않고 Strategy가 광고하므로
child를 다른 Strategy(예: ReAct)로 띄우면 그 child는 spawn_agent를 보지 못한다 — 조합 시 의도된 격리.

### Child Agent Spawn

Recursive Strategy가 Agent를 직접 생성하지 않고 **Runtime의 spawn 기능**을 사용한다
([ADR-0004](../adr/0004-child-spawn-via-runtime.md)):

```python
child_result = await runtime.spawn_agent(
    task=subtask,
    parent_context=context,
    context=sub_context,      # 선택 — child의 variables['context']
)
```

```text
Tool(spawn_agent | llm_query) → runtime.spawn_agent() → Child Context → Child Strategy
                                                              → Result(계약) → 관찰
```

**상속 규칙**: 미지정 인자는 parent 것을 상속한다 — child는 기본적으로 parent의
instructions/strategy/provider/tools/memory/config를 물려받고, `instructions`·`strategy`·`provider`는
오버라이드할 수 있다 (RLM의 "말단 노드는 가벼운 모델" 전략 지원, [ADR-0006](../adr/0006-runtime-per-run.md)).
Runtime 인스턴스 자체는 새로 만들지 않고 parent 것을 공유한다 — 예산과
Execution Tree가 run 전체에서 하나여야 하기 때문이다.

`spawn_agent`는 async다. 초기 구현은 순차 실행이지만, RLM 논문이 한계로 지적한
동기 재귀의 지연 문제를 고려해 **여러 child의 병렬 실행(`asyncio.gather` 수준)이
가능하도록 인터페이스를 유지**한다.

### Context 격리

Child Agent는 독립적인 Context를 가진다. parent의 messages·variables는 넘어가지 않는다 —
`context` 인자로 넘긴 **조각만** child의 `variables['context']`가 된다.

```text
Root Context                          Child Context
├── instructions (원본)               ├── instructions (상속 또는 지정)
├── messages: User Task, ...          ├── messages: Subtask
└── variables: context(거대 입력)     └── variables: context(조각만)
```

### 결과 계약 (Result Contract)

Child의 전체 Context를 Parent에게 전달하지 않는다. **필요한 결과만** 정해진 형태로
반환하여 Parent의 관찰이 된다. 이것이 재귀에서 context 폭발을 막는 장치다.

```json
{
  "status": "completed | failed | budget_exceeded",
  "result": "...",
  "evidence": [],
  "metadata": {}
}
```

- `status` — Parent가 실패·예산 초과를 구분해 대응할 수 있어야 한다.
- `result` — `budget_exceeded`여도 child가 마지막으로 낸 텍스트가 담긴다(partial).
- `evidence` — 검증(Reflection 등)에 쓸 근거. RLM의 "작은 문맥 검증" 패턴 지원.
- Child 내부의 메시지 히스토리·tool 결과는 **계약에 포함되지 않는다.**

### 재귀 제어

무한 재귀와 비용 폭발 방지는 Strategy가 아니라 Runtime의 책임이다:
`max_depth`, `max_children`, `max_iterations`, `token_budget`, `timeout`
([runtime.md](runtime.md#execution-control)).

## RLM Strategy — 문맥을 환경으로 다루는 재귀

**RLM은 별도의 Tool이 아니라 Strategy**다 ([ADR-0001](../adr/0001-rlm-as-recursive-strategy.md),
배경은 [rlm-background.md](../overview/rlm-background.md)). 다만 Recursive와 층위가 다르다:
Recursive가 *제어 흐름*(child 실행)이라면 RLM은 *데이터 흐름* — 거대 입력을 메시지가 아닌
**변수(Environment)**로 두고 코드로만 다루며, 조각만 child에 내려보낸다.

```text
RLM = ReAct loop + PythonTool(REPL, 네임스페이스 = Context.variables) + llm_query → spawn_agent
      + 환경 설명 instructions + Runtime 한도
```

```python
class RLMStrategy(ReActStrategy):
    default_tools = (PythonTool(),)                 # registry에 'python'이 있으면 그것을 쓴다(샌드박스 교체점)
    prompt = RLM_PROMPT                             # = REACT_PROMPT + REPL/llm_query 규칙 + 작업 패턴

    def environment(self, context):                 # 현재 변수 목록(이름/타입/len) — 호출마다 갱신
        return '## Current variables\n' + _describe_variables(context.variables)
```

흐름:

1. `Agent.run(task, context=big)` → `Context.variables['context'] = big`. 메시지에는 올라가지 않는다.
2. system 지시가 "변수 `context: str, len=N`이 있다, python tool로만 접근, `llm_query`로 위임,
   답은 tool 없이 텍스트로"를 알려준다.
3. 모델이 `python` tool로 `len(context)`, 슬라이스, 정규표현식으로 살핀다. REPL 상태(변수)는
   호출 간 유지된다 — 네임스페이스가 `context.variables` 그 자체이기 때문.
4. 코드 안에서 `llm_query(prompt, context=chunk)` → `env.runtime.spawn_agent(prompt, env.context,
   context=chunk)` → child는 `variables['context'] = chunk`와 상속된 지시로 같은 RLMStrategy를
   돈다(다시 재귀 가능). 반환은 child의 `result` 문자열. 루프로 수백 번 불러도 모델의 tool call은 하나다.
5. 부분 답을 변수에 모아 최종 답을 텍스트로 낸다. 관찰은 `max_output`으로 잘라 window를 보호한다.

`llm_query`는 모델 코드에서 동기 함수처럼 보이지만 exec가 worker thread에서 돌고
`run_coroutine_threadsafe`로 이벤트 루프의 child 실행을 기다린다. **PythonTool은 샌드박스가 없다**
(프로세스 권한으로 exec) — 신뢰된 환경 전용이며, 격리가 필요하면 같은 `name='python'`/schema로
Docker·원격 커널 Tool을 만들어 `Agent(tools=[...])`에 등록하면 RLMStrategy가 그것을 쓴다. 교체 Tool의
계약은 이름·schema만이 아니다: **`llm_query(prompt, context=None)`를 네임스페이스에 주입**하고
`env.runtime.spawn_agent`로 연결해야 한다 — `RLM_PROMPT`가 그 함수를 전제하기 때문이다.

### Recursive vs RLM

둘 다 `ReActStrategy` + `default_tools` 하나 차이다. Recursive는 **제어 흐름**(child를 띄운다),
RLM은 **데이터 흐름**(거대 입력을 변수로 두고 코드로 조각내 child에 내려보낸다).

| | RecursiveStrategy | RLMStrategy |
|---|---|---|
| 추가되는 tool | `spawn_agent` | `python` (REPL) |
| 재귀 트리거 | 모델이 **tool call로 직접** `spawn_agent(task, context=...)` | 모델이 쓴 **코드 안에서** `llm_query(prompt, context=chunk)` |
| tool call 1번당 child | 1개 | N개 (`for chunk in chunks: llm_query(...)`) |
| 거대 입력 | 없음 — 모델이 window 안에서 task를 말로 분해 | `Agent.run(task, context=big)` → `variables['context']`. messages에 올라가지 않고 모델은 `len`·슬라이스·정규식으로만 본다 |
| 상태 | 없음 | REPL 상태가 `context.variables`에 유지 — child 답을 변수에 모아 집계 |
| system 지시 | 원본 + `RECURSIVE_PROMPT`(ReAct 규칙 + 위임 규칙) | 원본 + `RLM_PROMPT`(ReAct 규칙 + REPL/llm_query 규칙) + `environment`(변수 목록 `context: str, len=N`) |
| 메커니즘 | `env.runtime.spawn_agent()` | 같음 |

언제 뭘 쓰나:

- **Recursive** — 문제가 *개념적으로* 쪼개질 때. "오픈소스 조사 / 상용 조사로 나눠라"(`examples/recursive.py`).
  모델이 하위 task를 문장으로 만들 수 있으면 충분하다.
- **RLM** — 입력이 *물리적으로* window를 넘을 때. 책 한 권에서 장별 숫자 합산(`examples/rlm.py`).
  모델은 전체를 못 보므로 "tool call 하나에 조각 하나를 인자로 인라인"하는 Recursive 방식으로는
  분할 정복이 성립하지 않는다 — 트리거를 코드(REPL) 쪽에 둬야 루프가 가능하다(ADR-0007의 동기).

RLM child는 같은 RLMStrategy를 상속하므로 자기 조각에 대해 다시 `python`/`llm_query`를 쓸 수 있다 —
즉 RLM ⊃ Recursive에 가깝고, Recursive는 "REPL 없이 가벼운 위임만 필요할 때"의 얇은 버전이다.

## Reflection Strategy

```text
Generate → Critique → Revision → Critique → Final
```

**스스로 `generate`를 부르지 않는 첫 전략**이다. 초안·비판·수정을 전부 child로 띄우는
오케스트레이터이므로, 비판자의 문맥 격리가 공짜로 따라온다 — child는 parent의 대화를 보지
못한다는 기존 불변식이 그대로 "자기 초안에 물들지 않은 비판자"가 된다.

```python
class ReflectionStrategy(Strategy):
    rounds: int = 2                  # 고정. 조기 종료 없음
    worker: Strategy = ReActStrategy()   # 초안·수정 child의 전략
    critic_prompt: str = REFLECTION_CRITIC_PROMPT
```

결정 사항:

- **`spawn_agent(strategy=self.worker)`는 선택이 아니라 필수** — 생략하면 child가 parent의
  전략(=ReflectionStrategy)을 상속해 `max_depth`까지 재귀한다
  ([ADR-0006](../adr/0006-runtime-per-run.md)). Phase 8의 `spawn_agent(strategy=...)`가
  죽은 유연성이 아니라 배관인 첫 사례.
- **조기 종료를 두지 않는다** — 비판자에게 "이제 충분한가"를 묻는 순간 모델이 스스로
  만족했는지 판단하게 되고, 그것을 막는 것이 이 패턴의 존재 이유다. 끄려면 `rounds=0`.
- **초안은 `context=`가 아니라 task 문자열로 넘긴다** — `spawn_agent(context=...)`는
  child의 `variables['context']`에 들어가고, 그것은 REPL(RLM)이 있어야 보인다.
  worker가 ReAct면 조용히 보이지 않으므로 넘기지 않는다.
- **비판자의 system은 사용자 지시 + `critic_prompt`** — 사용자가 "한국어로"를 걸었으면
  비판 라운드에서도 유지되어야 한다.
- **이 노드에는 `max_iterations`가 걸리지 않는다** — `generate`를 직접 부르지 않기 때문이다.
  실질 상한은 `max_children`(child 수 = `1 + rounds*2`)이고, 초과분은 계약으로 돌아와
  루프를 끝내며 지금까지의 최선을 답으로 삼는다. 그 공식은 전략이 `limits`로 제안하므로
  `rounds=4`도 별도 설정 없이 돈다 ([ADR-0014](../adr/0014-strategy-proposes-limits.md)).
- **중간 초안은 `evidence`에, 최신 초안 하나만 `context.messages`에** — 취소·한도로 끊겨도
  `last_assistant_text()`가 살리고, 멀티턴 transcript에는 중간 초안이 쌓이지 않는다.
- **`SpawnAgentTool`에는 `strategy`를 노출하지 않는다** — 모델이 전략을 고르게 하려면
  문자열 → 클래스 레지스트리가 필요해지고, 그것은 소비자 없이 Phase 9(Plugin)를 앞당긴다.
  전략 조합은 코드가 정한다.

검증: `tests/test_reflection.py`, `examples/reflection.py`.

## Router Strategy

쿼리 하나에 대해 **어느 Strategy가 최선인지** 고르고, 고른 Strategy가 끝까지 푼다.
supervisor(작업 분해·위임)가 아니라 바깥 껍데기다 — 문제를 "푸는" 패턴이 아니라 "배분하는" 패턴.

```text
Task → (규칙: variables['context'] 있음 → rlm) → 없으면 generate 1회로 분류 → 고른 전략을 같은 Context에서 실행
```

```python
RouterStrategy(
    {'react': ReActStrategy(), 'rlm': RLMStrategy(), 'reflection': ReflectionStrategy()},
    default='react',            # 분류 실패는 전체 실패이므로 필수 인자
    context_route='rlm',        # 거대 입력이 오면 묻지 않고 갈 곳. None이면 규칙을 끈다
)
```

결정 사항:

- **각 Strategy는 `description`("언제 나를 쓰나" 한 줄)을 갖는다** — `Tool.description`과 대칭.
  라우터가 routes의 description을 모아 분류 프롬프트를 만든다. 비어 있으면 클래스 이름으로
  대신하므로 **커스텀 전략이 이걸 몰라도 라우팅에 낀다**.
- **분류는 free-text가 아니라 tool call** — `route(strategy: enum[routes])`를 광고해 `generate`
  1회, `tool_calls[0].arguments['strategy']`를 읽는다. enum이라 고를 수 있는 값이 스키마로
  고정된다("아마 Reflection이 좋을 것 같은데 ReAct도…" 같은 답이 불가능해진다).
  텍스트로 답하면 `default`.
- **결정적 규칙이 모델보다 먼저** — `variables['context']`가 있다는 것은 "한 윈도우에 안
  들어간다"는 *사실*이지 판단이 아니다. 모델에게 물으면 토큰만 쓰고 틀릴 기회만 준다.
  이 경우 `generate`는 0회다.
- **고른 전략을 같은 Context에서 직접 실행한다** — `spawn_agent`로 child를 띄우지 않는다.
  child는 `messages=[task]` 하나뿐이라 대화 이력을 못 보므로, 라우터를 씌우는 순간 멀티턴이
  깨진다 (ADR-0010). 대신 Execution Tree에 별도 노드가 생기지 않으므로 "왜 이 전략인가"는
  `result.metadata['route']`와 `router.selected` 로그에 남긴다.
  (이 절의 이전 판은 child로 띄우라고 적혀 있었다 — 멀티턴이 생기기 전에 쓴 문장이다.)
- **확장 지점 셋**: `routes`(아무 Strategy나), `context_route`(규칙이 갈 곳), `classify()`
  (분류 로직 전체 — 규칙 기반·임베딩 기반으로 갈아끼우거나 분류만 싼 모델로 돌리는 것도 여기).

실측(vLLM `Gemma4-12B-it`): 5개 과제 중 4개를 기대대로 라우팅했고, 5번 모두 유효한 tool call을
냈다(`default` 폴백 0회). 같은 모델이 RLM의 다단계 오케스트레이션에서는 무너졌던 것과 대비된다 —
enum 하나를 고르는 일은 작은 모델에도 무겁지 않다. 분류를 싼 모델로 돌리는 근거이기도 하다.

검증: `tests/test_router.py`, `examples/router.py`.

## Strategy Composition (Phase 8)

장기적으로 Strategy는 단일 패턴 선택을 넘어 조합될 수 있어야 한다:

```text
Recursive
 └── ReAct          # child agent가 ReAct로 동작
      └── Reflection  # 결과를 Reflection으로 검증
```

이를 위해 Strategy를 enum이나 if/else가 아닌 독립적인 실행 abstraction으로 만든다.
조합의 자연스러운 형태: `spawn_agent(strategy=...)`로 child의 strategy를 지정한다.
`ReflectionStrategy`가 이 인자의 첫 소비자이고, `ReflectionStrategy(worker=RecursiveStrategy())`
처럼 worker를 갈아끼우면 위 조합이 그대로 성립한다 (`tests/test_reflection.py`).

## Custom Strategy

프레임워크에 없는 새로운 패턴을 사용자가 직접 구현할 수 있어야 한다.

```python
class MyStrategy(Strategy):

    async def execute(self, context, runtime):
        ...  # runtime.generate / execute_tool / spawn_agent / memory / execution 사용 가능
```

Custom Strategy도 Runtime의 공통 capability를 동일하게 사용한다 —
이것이 프레임워크의 핵심 확장 포인트다. 한도를 몰라도 Runtime이 막아 준다.
