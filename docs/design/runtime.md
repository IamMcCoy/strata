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

- Provider Registry / Tool Registry / Memory
- Agent Factory (spawn)
- Context Management
- Execution Management (Execution Tree)
- Budget Management (실행 한도)
- Event Dispatch / Tracing

```python
class Runtime:

    provider
    tools
    memory
    config              # RuntimeConfig
    execution_manager
    event_bus

    async def spawn_agent(self, task, parent_context,
                          strategy=None, provider=None) -> AgentResult: ...
    async def execute_tool(self, name, arguments): ...
```

Strategy는 Runtime이 제공하는 primitive를 통해 Provider, Tool, Memory,
Child Agent에 접근한다. Strategy가 이들을 직접 들고 있지 않게 하는 이유는
[ADR-0004](../adr/0004-child-spawn-via-runtime.md) 참조.

### Runtime의 수명

**Runtime 인스턴스는 run당 하나다** ([ADR-0006](../adr/0006-runtime-per-run.md)).
token budget과 Execution Tree는 run 전체(root + 모든 child)에 걸친 전역 상태이므로,
root Agent가 runtime 미지정 시 생성하고 child는 `spawn_agent`가 같은 인스턴스를
공유시킨다. 진입점은 `Agent.run(task)` 하나 — child 실행은 `spawn_agent` 내부의
책임이며, spawn 시 미지정 인자는 parent 것을 상속한다(`strategy`/`provider` 오버라이드 가능).

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

```python
RuntimeConfig(
    max_depth=5,        # 재귀 깊이 상한
    max_iterations=30,  # strategy 루프 상한
    max_children=8,     # 노드당 child 수 상한
    token_budget=100000,  # 전체 실행의 토큰 예산 (ModelResponse.usage 표준 키로 집계)
    timeout=300,        # 초 단위, run 전체 기준
)
```

한도 도달 시 예외로 터뜨리지 않고 `status: budget_exceeded` 로 현재까지의 결과를
반환하는 것을 기본 동작으로 한다 — RLM 방법론의 "예산 소진 시 현재 결과 반환"과 동일.

## Event System

Runtime의 주요 lifecycle을 Event로 노출한다.

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
