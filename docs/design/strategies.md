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
**Runtime이 제공하는 primitive를 통해** 접근한다:

```python
runtime.provider
runtime.tools
runtime.memory
runtime.spawn_agent()
runtime.execution
runtime.events
```

초기 구현: `ReActStrategy`, `RecursiveStrategy`.
향후: `ReflectionStrategy`, `PlanExecuteStrategy`, `RouterStrategy`,
`DebateStrategy`, `SelfConsistencyStrategy`, `MultiAgentStrategy`, `CustomStrategy`.
각 패턴의 배경과 Strata primitive 매핑은
[agentic-patterns-background.md](../overview/agentic-patterns-background.md) 참조.

## ReAct Strategy

Tool을 반복적으로 사용하며 문제를 해결하는 패턴.

```text
Task → LLM → Action → Tool → Observation → LLM → ... → Final Answer
```

```python
class ReActStrategy(Strategy):

    async def execute(self, context, runtime):

        for _ in range(runtime.config.max_iterations):

            response = await runtime.provider.generate(
                context.messages,
                tools=list(runtime.tools.values()),
            )

            if not response.tool_calls:
                return AgentResult(result=response.text)

            for call in response.tool_calls:
                result = await runtime.execute_tool(call.name, call.arguments)
                context.add_tool_result(result)

        return AgentResult(status='budget_exceeded')
```

tool call의 Provider별 형식 차이는 `ModelResponse.tool_calls`(`ToolCall`)가
흡수한다 — Strategy는 파싱하지 않는다
([abstractions.md](abstractions.md#provider)). 반복 한도 값은
`RuntimeConfig.max_iterations`가 정의하고, `token_budget`·`timeout`은 Runtime이
provider/tool 호출 시점에 강제한다 ([runtime.md](runtime.md#execution-control)).

## Recursive Strategy / RLM

**RLM은 별도의 Tool이 아니다.** Agent가 문제 해결 과정에서 새로운 Agent Execution을
생성할 수 있도록 하는 Recursive Agent Strategy로 구현한다
([ADR-0001](../adr/0001-rlm-as-recursive-strategy.md), 배경은
[rlm-background.md](../overview/rlm-background.md)).

```text
Root Agent
    ├── Tool
    ├── Tool
    └── Child Agent
            ├── Tool
            └── Child Agent
                    └── ...
```

### Child Agent Spawn

Recursive Strategy가 Agent를 직접 생성하지 않고 **Runtime의 spawn 기능**을 사용한다
([ADR-0004](../adr/0004-child-spawn-via-runtime.md)):

```python
child_result = await runtime.spawn_agent(
    task=subtask,
    parent_context=context,
)
```

```text
RecursiveStrategy → runtime.spawn_agent() → Child Agent → Child Execution
                                                              → Result → Parent Context
```

**상속 규칙**: 미지정 인자는 parent 것을 상속한다 — child는 기본적으로 parent의
provider/tools/memory/config를 물려받고, `strategy`와 `provider`는 오버라이드할 수
있다 (RLM의 "말단 노드는 가벼운 모델" 전략 지원, [ADR-0006](../adr/0006-runtime-per-run.md)).
Runtime 인스턴스 자체는 새로 만들지 않고 parent 것을 공유한다 — 예산과
Execution Tree가 run 전체에서 하나여야 하기 때문이다.

`spawn_agent`는 async다. 초기 구현은 순차 실행이지만, RLM 논문이 한계로 지적한
동기 재귀의 지연 문제를 고려해 **여러 child의 병렬 실행(`asyncio.gather` 수준)이
가능하도록 인터페이스를 유지**한다.

### Context 격리

Child Agent는 독립적인 Context를 가진다:

```text
Root Context                    Child Context
├── User Task                   ├── Subtask
├── Global Instructions         ├── Local State
└── Child Results               └── Tool Results
```

### 결과 계약 (Result Contract)

Child의 전체 Context를 Parent에게 전달하지 않는다. **필요한 결과만** 정해진 형태로
반환하여 Parent Context에 추가한다. 이것이 재귀에서 context 폭발을 막는 장치다.

```json
{
  "status": "completed | failed | budget_exceeded",
  "result": "...",
  "evidence": [],
  "metadata": {}
}
```

- `status` — Parent가 실패·예산 초과를 구분해 대응할 수 있어야 한다.
- `evidence` — 검증(Reflection 등)에 쓸 근거. RLM의 "작은 문맥 검증" 패턴 지원.
- Child 내부의 메시지 히스토리·tool 결과는 **계약에 포함되지 않는다.**

### 재귀 제어

무한 재귀와 비용 폭발 방지는 Strategy가 아니라 Runtime의 책임이다:
`max_depth`, `max_children`, `token_budget`, `timeout`
([runtime.md](runtime.md#execution-control)).

## Reflection Strategy (Phase 7)

```text
Generate → Critique → Revision → Critique → Final
```

## Strategy Composition (Phase 8)

장기적으로 Strategy는 단일 패턴 선택을 넘어 조합될 수 있어야 한다:

```text
Recursive
 └── ReAct          # child agent가 ReAct로 동작
      └── Reflection  # 결과를 Reflection으로 검증
```

이를 위해 Strategy를 enum이나 if/else가 아닌 독립적인 실행 abstraction으로 만든다.
조합의 자연스러운 형태: `spawn_agent`에 child의 strategy를 지정할 수 있게 한다.

## Custom Strategy

프레임워크에 없는 새로운 패턴을 사용자가 직접 구현할 수 있어야 한다.

```python
class MyStrategy(Strategy):

    async def execute(self, context, runtime):
        ...  # runtime.provider / tools / memory / spawn_agent / events 사용 가능
```

Custom Strategy도 Runtime의 공통 capability를 동일하게 사용한다 —
이것이 프레임워크의 핵심 확장 포인트다.
