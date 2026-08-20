# Strata Architecture

## 전체 구조

```text
                         Agent Runtime
                              │
       ┌──────────┬───────────┼───────────┬───────────┐
       │          │           │           │           │
   Provider     Tools      Strategies    Memory    Execution
       │          │           │           │           │
       │          │      ┌────┼────┐      │       Trace
       │          │      │    │    │      │       Events
       │          │    ReAct Recursive Reflection
       │          │           │
       └──────────┴───────────┼───────────┘
                              │
                           Context
                              │
                            Agent
```

Runtime은 각 구성요소를 직접 구현하지 않는다. **각 abstraction을 연결하고
실행 lifecycle을 관리한다.**

## 컴포넌트 책임

| 컴포넌트 | 책임 | 설계 문서 |
|---|---|---|
| Provider | LLM 통신 추상화. Strategy는 특정 Provider API를 직접 호출하지 않는다 | [abstractions.md](../design/abstractions.md#provider) |
| Tool | 외부 시스템·환경과의 상호작용 | [abstractions.md](../design/abstractions.md#tool) |
| Memory | 실행 간 영속 정보의 저장과 검색 | [abstractions.md](../design/abstractions.md#memory) |
| Context | 현재 실행의 상태 (messages, tool_results, child_results, …) | [abstractions.md](../design/abstractions.md#context) |
| Strategy | 문제 해결의 실행 패턴. **프레임워크의 핵심 확장 포인트** | [strategies.md](../design/strategies.md) |
| Agent | Provider + Strategy + Tools + Memory 를 조합한 실행 단위 | [abstractions.md](../design/abstractions.md#agent) |
| Runtime | Registry, spawn, 실행 한도, 이벤트 등 공통 실행 환경 | [runtime.md](../design/runtime.md) |
| Execution | 실행을 Tree 구조로 추적 (특히 Recursive에서) | [runtime.md](../design/runtime.md#execution-tree) |
| Event | lifecycle을 이벤트로 노출 — logging/tracing/cost 추적의 기반 | [runtime.md](../design/runtime.md#event-system) |

## Context와 Memory의 관계

```text
                 Agent
                   │
          ┌────────┴────────┐
          │                 │
       Context            Memory
          │                 │
     Current State      Persistent State
       (현재 실행)        (실행 간 유지)
```

Memory의 정보는 Retrieve를 거쳐 현재 Context에 주입된 뒤 Strategy가 사용한다:

```text
Memory → Retrieve → Context → Strategy
```

예: "지난번 프로젝트 구조를 기반으로 API를 설계해줘" 라는 요청이 오면,
Memory에서 `FastAPI`, `PostgreSQL`, `JWT` 등 관련 정보를 Retrieve하여 Context에 주입한다.
분리 근거는 [ADR-0002](../adr/0002-context-memory-separation.md) 참조.

## 실행 흐름

```text
                    User Task
                       │
                       ▼
                     Agent
                       │
                       ▼
                    Strategy
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Memory        Provider      Tools
          │            │            │
          └────────────┼────────────┘
                       ▼
                    Context
                       │
                       ▼
                   Execution
```

일반적인 실행 순서:

1. Agent가 Task 수신
2. Memory에서 관련 정보 Retrieve
3. Context 구성
4. Strategy 실행
5. Provider를 통해 LLM 호출
6. Tool 필요 시 Runtime을 통해 Tool 실행
7. 결과를 Context에 반영
8. 필요하면 Child Agent Spawn (`runtime.spawn_agent`)
9. Execution Tree 업데이트
10. 필요한 정보를 Memory에 Store
11. 최종 Result 반환

## 저장소 구조

```text
strata/
│
├── src/strata/
│   ├── agent/          # Agent, Context, (state)
│   ├── strategies/     # Strategy base + react / recursive / reflection
│   ├── providers/      # Provider base + openai / anthropic / vllm / ...
│   ├── tools/          # Tool base + registry
│   ├── memory/         # Memory base + in_memory / ...
│   ├── runtime/        # Runtime, Execution, RuntimeConfig(budget/limits)
│   └── tracing/        # Trace, Events
│
├── tests/
├── examples/           # react.py, recursive.py, reflection.py (Phase 2+)
├── docs/
├── pyproject.toml
└── README.md
```
