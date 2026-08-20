# Agentic Patterns 배경

Strata가 Strategy로 지원(예정)하는 주요 Agentic Pattern들의 배경 지식.
RLM/Recursive는 별도 문서([rlm-background.md](rlm-background.md)) 참조.
각 패턴이 Strata의 어떤 primitive로 분해되는지를 함께 정리한다 —
**모든 패턴은 `Strategy.execute(context, runtime)` 하나의 인터페이스로 표현된다.**

## ReAct (Reason + Act)

> Yao et al., 2022 — "ReAct: Synergizing Reasoning and Acting in Language Models"

추론(Reasoning)과 행동(Acting)을 교대로 수행하는 가장 기본적인 agent 패턴.
모델이 생각(Thought)을 서술하고 → 행동(Action, 주로 tool call)을 선택하고 →
관찰(Observation)을 받아 다음 추론에 반영하는 루프를 최종 답까지 반복한다.

```text
Task → Thought → Action(Tool) → Observation → Thought → ... → Final Answer
```

- **강점**: 단순하고 범용적. 외부 정보가 필요한 대부분의 작업에 기본값.
- **약점**: 루프가 길어지면 context가 선형으로 누적되어 오염(Context Rot)되고,
  중간에 잘못 든 길을 스스로 교정하기 어렵다.
- **Strata 매핑**: `ReActStrategy` = `runtime.generate()` +
  `runtime.execute_tool()` 루프. 루프 상한은 `runtime.generate`가 `max_iterations`로 강제.
  Phase 2에서 최초 구현.

## Reflection / Self-Refine

> Madaan et al., 2023 — "Self-Refine"; Shinn et al., 2023 — "Reflexion"

생성한 결과를 모델 스스로(또는 별도의 critic 역할로) 비평하고 수정하는 패턴.
생성자와 비평자를 같은 모델의 다른 프롬프트로 나누는 것만으로도 품질이 오른다.

```text
Generate → Critique → Revision → Critique → ... → Final
```

- **강점**: 코드, 글쓰기 등 "정답 검증이 생성보다 쉬운" 작업에서 효과가 큼.
- **약점**: 반복당 비용이 배로 들고, 비평자가 같은 모델이면 같은 맹점을 공유한다.
  RLM 실험에서 관찰된 과잉 검증(이미 맞은 답을 반복 검증하다 오답 선택)도 같은 계열의 위험.
- **Strata 매핑**: `ReflectionStrategy`(Phase 7). Critique를 같은 context에서 할 수도,
  깨끗한 작은 context를 위해 `runtime.spawn_agent()`로 분리할 수도 있다 —
  후자가 RLM의 "작은 문맥 검증" 패턴과 정확히 같은 구조다.

## Plan & Execute

> Wang et al., 2023 — "Plan-and-Solve"; ReWOO, LLMCompiler 계열

작업 전체의 계획을 먼저 세우고(Planner), 각 step을 실행(Executor)한 뒤,
필요하면 결과를 보고 재계획(Re-plan)하는 패턴. ReAct가 한 걸음씩 더듬어 가는
방식이라면, 이쪽은 지도를 먼저 그린다.

```text
Task → Plan(step 1..N) → Execute step → (관찰 후 Re-plan) → ... → Final
```

- **강점**: 다단계 작업에서 방향 상실이 적고, 독립적인 step은 병렬 실행이 가능하다.
  Planner와 Executor에 다른 모델을 쓸 수 있어(계획은 큰 모델, 실행은 작은 모델) 비용 효율적.
- **약점**: 초기 계획이 틀리면 전체가 흔들린다 — 재계획 루프가 사실상 필수.
- **Strata 매핑**: `PlanExecuteStrategy`. 각 step 실행을 `spawn_agent`로 위임하면
  Recursive와 자연스럽게 합쳐진다 (step별 독립 Context + 결과 계약).

## Router

입력을 분류해 적합한 하위 agent / strategy / 모델로 위임하는 패턴.
문제를 "푸는" 패턴이 아니라 "배분하는" 패턴이다.

```text
Task → Classify → route A | route B | route C → 해당 agent 실행 → Result
```

- **강점**: 이질적인 요청이 섞여 들어오는 시스템의 진입점. 쉬운 요청은 싼 모델로,
  어려운 요청만 비싼 파이프라인으로 보내 비용을 제어한다.
- **약점**: 라우팅 자체가 잘못되면 이후 전 과정이 무의미. 분류 기준의 유지보수 비용.
- **Strata 매핑**: `RouterStrategy` = 분류 1회 호출 + `spawn_agent(strategy=...)`.
  child의 strategy를 지정하는 spawn 인터페이스([ADR-0004](../adr/0004-child-spawn-via-runtime.md))가
  그대로 라우팅 테이블이 된다.

## Debate / Multi-Agent Discussion

> Du et al., 2023 — "Improving Factuality and Reasoning through Multiagent Debate"

여러 agent가 같은 문제에 대해 각자 답을 내고, 서로의 답을 보고 반박·수정하는
라운드를 거친 뒤 수렴하거나 판정자(Judge)가 최종 결정하는 패턴.

```text
Task → Agent A/B/C 각자 답변 → 서로의 답 교환 → 반박/수정 라운드 × R → Judge → Final
```

- **강점**: 사실성·추론 문제에서 단일 모델의 편향과 맹점을 상쇄. 관점 다양성이 핵심이라
  서로 다른 프롬프트/모델을 섞을수록 효과가 크다.
- **약점**: 비용이 참가자 수 × 라운드 수로 곱해진다. 다수가 틀리면 오답으로 수렴하는
  동조(conformity) 현상도 보고됨.
- **Strata 매핑**: `DebateStrategy` = N개의 `spawn_agent`(병렬) + 라운드 루프 + 판정 호출.
  async `spawn_agent` 설계가 여기서도 전제 조건이다.

## Self-Consistency

> Wang et al., 2022 — "Self-Consistency Improves Chain of Thought Reasoning"

같은 문제를 온도를 높여 여러 번 독립적으로 풀게 한 뒤, 답들 사이의
다수결(majority voting)로 최종 답을 정하는 패턴. Debate와 달리 agent 간 상호작용이 없다.

```text
Task → 독립 시도 × N (병렬) → 답 집계 → 다수결 → Final
```

- **강점**: 구현이 가장 단순한 앙상블. 수학·논리처럼 답이 이산적인 문제에서 효과적.
- **약점**: 답이 자유 서술형이면 "같은 답"의 판정이 어렵다. 비용 N배.
- **Strata 매핑**: `SelfConsistencyStrategy` = 병렬 `provider.generate()` × N + 집계.
  spawn 없이 Provider 호출만으로 충분한, 가장 가벼운 multi-sample 패턴.

## Multi-Agent Orchestration

역할이 분화된 여러 agent(researcher, coder, reviewer, …)가 협업하는 일반화된 패턴.
Debate가 "같은 문제, 다른 의견"이라면 이쪽은 "다른 역할, 하나의 목표"다.
supervisor(orchestrator)가 작업을 나눠 worker들에게 위임하는 형태가 대표적.

```text
Supervisor → task 분해 → Worker A(researcher) / Worker B(coder) → 결과 수합 → Synthesis
```

- **강점**: 역할별로 다른 tool·prompt·모델을 최적화할 수 있고, worker의 context가
  격리되어 각자의 작업에 집중한다.
- **약점**: agent 간 통신 프로토콜이 곧 복잡성이다. 역할 분화가 과하면
  단일 agent보다 못한 결과에 비용만 커진다.
- **Strata 매핑**: `MultiAgentStrategy`는 사실상 RecursiveStrategy의 특수화 —
  supervisor가 root, worker가 child이며, 역할 차이는 spawn 시 지정하는
  strategy/tools/prompt의 차이일 뿐이다. 결과 계약과 Execution Tree를 그대로 재사용한다.

## 패턴 비교 요약

| 패턴 | 핵심 축 | 병렬성 | 주요 primitive | Phase |
|---|---|---|---|---|
| ReAct | 순차 tool 루프 | 없음 | `generate` + `execute_tool` | 2 |
| Recursive / RLM | 문제 분해 + 재귀 | 가능 (child) | `spawn_agent` (Tool이 트리거) | 3 |
| Reflection | 생성-비평 루프 | 없음 | `generate` (+`spawn_agent`) | 7 |
| Plan & Execute | 선계획 후실행 | 가능 (step) | `spawn_agent` | 향후 |
| Router | 분류 후 위임 | — | `spawn_agent(strategy=...)` | 향후 |
| Debate | 상호 반박 후 수렴 | 필수 (참가자) | `spawn_agent` 병렬 | 향후 |
| Self-Consistency | 독립 시도 다수결 | 필수 (시도) | `generate` 병렬 | 향후 |
| Multi-Agent | 역할 분담 협업 | 가능 (worker) | `spawn_agent` | 향후 |

표가 보여주는 것: **거의 모든 패턴이 `generate` / `execute_tool` / `spawn_agent`
세 primitive의 조합**이다. Strata가 패턴별 프레임워크가 아니라 primitive를 제공하는
Runtime으로 설계된 이유가 여기에 있다
([ADR-0003](../adr/0003-strategy-as-first-class-abstraction.md)).
