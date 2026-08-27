# Strata 프로젝트 개요

## 정의

**Strata**는 다양한 Agentic Pattern을 하나의 Runtime 위에서 구현하고 조합할 수 있도록 하는
**확장형 Agent Execution Framework**이다.

특정 LLM Provider, Tool, Memory, Agent Pattern에 종속되지 않도록 각각을 독립적인
abstraction으로 설계하고, Runtime이 이들을 유기적으로 연결하고 실행한다.

핵심은 RLM 자체를 구현하는 것이 아니라, **RLM을 포함한 다양한 Agent 실행 패턴을
동일한 인터페이스에서 구현하고 조합할 수 있는 기반을 만드는 것**이다.

> Strata — A composable runtime for agentic systems.

## Strata가 아닌 것

- **RLM Library가 아니다.** RLM은 Strata가 지원하는 여러 Strategy 중 하나다.
  ([ADR-0001](../adr/0001-rlm-as-recursive-strategy.md))
- **Tool Collection이 아니다.** Tool은 교체 가능한 abstraction일 뿐, 프레임워크의 정체성이 아니다.
- **특정 Provider의 SDK Wrapper가 아니다.** 동일한 Strategy가 OpenAI, Anthropic, vLLM 등
  어떤 Provider 위에서도 동작해야 한다.

## 핵심 설계 철학 — 책임의 분리

각 구성요소의 책임을 명확하게 분리한다.

| 구성요소 | 책임 |
|---|---|
| **Provider** | 어떤 모델을 사용할 것인가 |
| **Strategy** | 어떻게 문제를 해결할 것인가 |
| **Tool** | 무엇을 실행할 수 있는가 |
| **Memory** | 무엇을 기억하는가 (실행 간 영속) |
| **Context** | 현재 무엇을 알고 있는가 (현재 실행의 상태) |
| **Agent** | 위 요소들을 조합한 실행 단위 |
| **Runtime** | 전체 실행 환경과 lifecycle 관리 |
| **Execution** | 실행 과정과 상태 추적 |
| **Event** | 실행 과정에서 발생하는 이벤트 |

핵심적으로 다음을 분리한다:

```text
Agent    ≠ Strategy
Strategy ≠ Tool
Tool     ≠ Memory
Memory   ≠ Context
Provider ≠ Strategy
```

이 분리를 통해 특정 Provider나 Pattern에 종속되지 않는 구조를 만든다.

## 목표 사용 예

사용자는 구성 요소를 자유롭게 조합하고, **Strategy만 교체하여 실행 패턴을 바꿀 수 있어야 한다.**

```python
agent = Agent(
    provider=provider,                                   # OpenAIProvider(model, model_params={'temperature': 0.3})
    strategy=RecursiveStrategy(prompt=..., model_params={'temperature': 0}),  # 패턴 지시·샘플링 파라미터 덮어쓰기(선택)
    tools=[WebSearchTool(), PythonTool()],
    memory=memory,
    instructions='한국어로 답하라.',                       # 사용자 system 지시 — child가 상속
    config=RuntimeConfig(max_depth=5, max_iterations=30, token_budget=200_000),  # 한도는 Runtime이 강제
)

result = await agent.run("복잡한 문제를 분석하고 결과를 도출해줘")
```

같은 Agent abstraction에서 `strategy=ReActStrategy()`, `strategy=ReflectionStrategy()` 로
바꾸는 것만으로 실행 패턴이 교체된다. Agent 자체에는 특정 패턴의 실행 로직이 없다.

## 핵심 키워드

Composable · Extensible · Provider-agnostic · Tool-agnostic · Strategy-driven ·
Memory-aware · Recursive Agent · Agentic Patterns · Execution Runtime ·
Agent Orchestration · Plugin Architecture
