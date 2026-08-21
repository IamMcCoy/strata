# Runtime / Execution / Events

## Runtime

Runtime은 단순한 execute 함수가 아니다. **Agent 실행에 필요한 모든 리소스와
lifecycle을 관리하는 공통 실행 환경**이다.

```text
                         Runtime
                            │
        ┌───────────┬───────┼───────┬───────────┐
        │           │       │       │           │
    Provider      Tools   Memory  Execution   Events
        │           │       │       │           │
        └───────────┴───────┼───────┴───────────┘
                            │
                           Agent
                            │
                         Strategy
```

주요 책임:

- Provider / Tool Registry / Memory
- **세 primitive** — `generate` / `execute_tool` / `spawn_agent` (모든 패턴이 이 셋의 조합)
- Context Management (system 지시 조립, child Context 생성)
- Execution Management (Execution Tree)
- Budget Management (실행 한도·usage 집계)
- Event Dispatch / Tracing (Phase 6)

```python
class Runtime:

    provider
    tools               # name → Tool registry
    memory
    config              # RuntimeConfig
    execution           # ExecutionManager (Execution Tree)
    usage               # run 전체 누적 {input_tokens, output_tokens, total_tokens}
    default_strategy    # spawn 시 상속되는 strategy — root Agent가 설정

    async def generate(self, context, tools=None, instructions=None, **kwargs) -> ModelResponse: ...
    async def execute_tool(self, name, arguments, context, tools=None) -> Any: ...
    async def spawn_agent(self, task, parent_context, *, context=None,
                          instructions=None, strategy=None, provider=None) -> AgentResult: ...
    async def run_strategy(self, strategy, context) -> AgentResult: ...   # 한도 초과 → 계약 변환
```

### Primitive — Strategy가 리소스에 닿는 유일한 길

Strategy는 `runtime.provider`를 직접 호출하지 않는다 ([ADR-0008](../adr/0008-all-primitives-through-runtime.md)).
세 primitive가 전부 Runtime을 지나므로 한도·집계·이벤트가 한 곳에서 일어난다.

| primitive | 하는 일 |
|---|---|
| `generate(context, tools, instructions, **kwargs)` | `context.instructions`(또는 인자로 덮어쓴 지시)를 system 메시지로 앞에 붙여 Provider 호출. 노드당 호출 수(`max_iterations`)·run 전체 `token_budget` 검사, `usage` 누적. kwargs는 모델 파라미터 — `{**provider.model_params, **kwargs}`로 합쳐 전달(우선순위는 이 한 줄, [abstractions.md](abstractions.md#모델-파라미터-temperature-등)) |
| `execute_tool(name, arguments, context, tools)` | `ToolEnv(context, runtime)`를 첫 인자로 Tool 실행. **알 수 없는 tool·Tool 예외는 관찰 문자열로 반환** — 모델 실수로 run이 죽지 않는다. `tools`는 Strategy가 자체 tool(spawn_agent, python)을 광고할 때 넘기는 매핑(기본 registry) |
| `spawn_agent(task, parent_context, context=, instructions=, strategy=, provider=)` | child 생성·실행. `context`는 child의 `variables['context']`(sub-context), `instructions` 미지정 시 parent 것 상속, strategy/provider 미지정 시 상속. 한도 초과·child 예외는 `AgentResult` 계약으로 반환 |

Tool이 Runtime에 닿는 길도 하나다 — `Tool.execute(env, **kwargs)`의 `ToolEnv`
([ADR-0007](../adr/0007-spawn-trigger-is-a-tool.md)). `SpawnAgentTool`·`PythonTool.llm_query`가
이 경로로 `env.runtime.spawn_agent()`를 부르므로 "Tool에서 시작하는 재귀"도 Runtime 통제 안이다.

### Runtime의 수명

**Runtime 인스턴스는 run당 하나다** ([ADR-0006](../adr/0006-runtime-per-run.md)).
token usage와 Execution Tree는 run 전체(root + 모든 child)에 걸친 전역 상태이므로,
`Agent.run`이 매 run 시작 시 새로 만들고 child는 `spawn_agent`가 같은 인스턴스를
공유시킨다. 진입점은 `Agent.run(task, context=None)` 하나 — child 실행은 `spawn_agent` 내부의
책임이다. 같은 Agent를 두 번 돌려도 usage·tree는 섞이지 않으며, 마지막 run의 Runtime은
`agent.runtime`으로 조회한다.

## Execution Tree

모든 Agent 실행은 Execution 단위로 관리한다.
특히 Recursive Agent에서 실행은 Tree 구조를 갖는다.

```text
Run
├── Root
├── Research A
│   ├── Search
│   └── Research A-1
├── Research B
│   └── Search
└── Synthesis
```

```python
class ExecutionNode:

    id: str
    parent_id: str | None

    task: str
    depth: int
    iterations: int      # 이 노드의 provider 호출 수 (max_iterations 집계 단위)

    status: str          # running | completed | failed | budget_exceeded
    result: AgentResult | None   # 결과 계약 그대로 보존

    children: list
```

초기에는 In-Memory로 구현하고, 이후 DB 또는 외부 Trace Backend(OpenTelemetry 등)로
확장할 수 있도록 abstraction을 유지한다
([ADR-0005](../adr/0005-execution-tree-in-memory-first.md)).

## Execution Control

Recursive Agent는 무한 재귀와 비용 폭발을 방지해야 한다.
**한도의 강제는 Strategy가 아니라 Runtime의 책임이다** — Strategy 구현이
바뀌어도(또는 Custom Strategy가 실수해도) 한도는 지켜져야 하기 때문이다.
세 primitive가 모두 Runtime을 지나기 때문에 실제로 그렇게 된다.

```python
RuntimeConfig(
    max_depth=5,        # 재귀 깊이 상한                 — spawn_agent에서 검사
    max_iterations=30,  # 노드당 provider 호출 상한      — generate에서 검사
    max_children=8,     # 노드당 child 수 상한           — spawn_agent에서 검사
    token_budget=None,  # run 전체 토큰 예산             — generate에서 검사 (usage 표준 키 집계)
    timeout=None,       # 초 단위, run 전체 기준         — Agent.run이 asyncio.timeout으로 적용
)
```

한도 도달 시 예외로 터뜨리지 않고 **`status: budget_exceeded` 로 현재까지의 결과를
반환**한다 — RLM 방법론의 "예산 소진 시 현재 결과 반환"과 동일:

- `spawn_agent`의 depth/children 초과 → child를 만들지 않고 `budget_exceeded` 계약 반환.
  모델은 이를 관찰로 받고 스스로 답한다.
- `generate`의 iterations/token 초과 → 내부 신호 `BudgetExceeded`를 올리고,
  `Runtime.run_strategy`가 `AgentResult(status='budget_exceeded',
  result=<마지막 assistant 텍스트>, metadata={reason, limit})`로 변환한다.
  Strategy는 이 예외를 몰라도 된다(잡아서 더 나은 partial을 만들 수는 있다).
- child의 일반 예외 → `status='failed'` 계약. root의 일반 예외는 숨기지 않고 전파한다
  (tree에는 failed로 남는다) — 프로그래밍 오류는 사용자가 봐야 한다.

## Event System

Runtime의 주요 lifecycle을 Event로 노출한다 (Phase 6). 발행 지점은 세 primitive와
`spawn_agent`/`run_strategy`로 이미 모여 있다.

```text
agent.started        agent.finished
strategy.started     strategy.finished
provider.request     provider.response
tool.started         tool.finished
memory.retrieve      memory.store
agent.spawned        agent.completed
execution.failed
```

Event 기반으로 확장하는 기능: Logging, Monitoring, Tracing, Token Usage,
Cost Tracking, Debugging, Visualization.

핵심 실행 경로는 Event 구독자의 존재 여부와 무관하게 동작해야 한다
(관찰이 실행에 영향을 주지 않는다).

## Plugin / Registry

장기적으로 Provider, Tool, Strategy, Memory를 Plugin 형태로 추가할 수 있도록
Registry 구조를 고려한다.

```python
register_strategy("my_strategy", MyStrategy)
register_provider("my_provider", MyProvider)
register_tool("my_tool", MyTool)
register_memory("my_memory", MyMemory)
```

초기에는 단순 dict 기반 Registry로 시작하고, 이후 Package/Plugin discovery
(entry points) 구조로 확장한다. (Phase 9)
