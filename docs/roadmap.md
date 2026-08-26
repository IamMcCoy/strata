# Roadmap — 구현 우선순위

각 Phase는 이전 Phase 위에 쌓인다. **완료 기준**을 만족하기 전에는 다음 Phase로 넘어가지 않는다.

## Phase 1 — Core Abstraction ✅

Agent, Provider, Tool, Memory, Strategy, Context, Runtime 인터페이스 확립.
**구현보다 abstraction 설계를 우선한다.**

- 완료 기준: `src/strata/` 에 모든 base 클래스가 존재하고, import 및 서브클래싱이
  가능하며, 인터페이스가 [design 문서](design/abstractions.md)와 일치한다.

## Phase 2 — ReAct ✅

최소 Tool Calling Loop.

```text
Agent → ReActStrategy → Provider → Tool → Observation → Loop
```

- 완료 기준: 실제 Provider 1개(또는 fake provider) + Tool 1개로
  `examples/react.py` 가 end-to-end로 동작한다.

## Phase 3 — Recursive / RLM (핵심 Phase) ✅

```text
Recursive: SpawnAgentTool → runtime.spawn_agent() → Child Context → Child Strategy → Result(계약) → 관찰
RLM:       PythonTool(REPL = Context.variables) → llm_query(prompt, context=chunk) → runtime.spawn_agent() → ...
```

동시에 Execution Tree, `max_depth`, `max_children`, `Context.instructions`, `ToolEnv`,
`Runtime.generate` 구현 (ADR-0007/0008). 이어서 전략별 harness prompt(`Strategy.prompt` +
`environment()`, `REACT/RECURSIVE/RLM_PROMPT`)와 모델 파라미터(`model_params`: Provider 기본값 <
Strategy, merge는 `Runtime.generate`)를 사용자 덮어쓰기 가능하게 추가 (`tests/test_strategy_prompt_params.py`).

- 완료 기준(Recursive): `examples/recursive.py` 에서 depth ≥ 2 의 재귀 실행이 동작하고,
  Execution Tree에 전체 tree가 기록되며, `max_depth` 초과 시 `budget_exceeded` 로 안전하게 종료된다.
- 완료 기준(RLM): `examples/rlm.py` 에서 거대 입력이 메시지가 아닌 `variables['context']`로
  들어가고, 모델 코드의 `llm_query` 루프가 조각만 가진 child를 여러 개 띄워 결과를 변수에 모은다.
  child의 system 지시에 자기 조각의 변수 설명이 들어간다.

## Phase 4 — Memory ✅

`InMemory` 구현 → 이후 Redis / Vector DB / SQL / Custom 을 연결할 수 있도록
인터페이스 유지. Memory Retrieve / Store lifecycle을 Runtime과 연결 —
retrieve는 `Agent.run`이 자동으로(→ `Context.instructions`), store는 `MemoryTool`로 명시적으로
([lifecycle 표](design/abstractions.md#lifecycle--흐름은-단방향-adr-0002)).

구현체는 `InMemory` / `SQLiteMemory`(stdlib) / `RedisMemory`(클라이언트 주입) 셋 —
런타임 의존성은 그대로 0개다. MariaDB·Postgres·Vector DB는 코어가 소유하지 않는다
([근거](design/abstractions.md#구현체--코어가-소유하는-셋)).

- 완료 기준: 실행 A에서 store한 정보가 실행 B의 Context에 retrieve되어 주입된다
  (`tests/test_memory.py`, `examples/memory.py`).
- 세 구현이 같은 계약 테스트를 통과한다. 실제 Redis·실제 멀티프로세스 검증은
  `make test-integration` (`tests/test_memory_integration.py`).

## 멀티턴 — Phase 4의 곁가지 (ADR-0010)

Memory와 자주 혼동되지만 다른 것이다: 대화 이력은 코어가 소유하지 않고
`Agent.run(task, history=...)` ↔ `result.metadata['messages']`로 앱과 주고받는다.

- 완료 기준: 턴 2가 턴 1의 대화를 보고, child의 `AgentResult`에는 transcript가 실리지 않는다
  (`tests/test_conversation.py`, `examples/conversation.py`).
- transcript는 순수 JSON이어야 한다 — 앱이 DB·큐에 저장하기 때문이다.
  큐 + task_id + 멀티 워커 전체 파이프라인은 `examples/worker.py`
  (검증: `tests/test_pipeline_integration.py`). 큐 자체는 코어에 두지 않는다 — Agent를
  직렬화할 수 없어 워커가 소유해야 하고, 그러면 브로커 선택은 앱의 몫이 된다.

## 취소와 식별자 — Phase 6의 전제 (ADR-0011)

`run_id`(UUIDv7)를 코어가 발급한다. `exec_0`은 run마다 재사용되므로 그것만으로는
프로세스·run을 넘는 기록이 뒤섞인다 — 로깅·실행 기록 영속화의 전제다.
취소는 하드(asyncio)와 협조적(`runtime.cancel()`) 두 종류이며, 후자는 이미 쓴 토큰을 살린다.

- 완료 기준: 협조적 취소가 부분 결과를 반환하고 새 child를 막으며, 하드 취소가
  tree에 `cancelled`로 남는다 (`tests/test_cancellation.py`, `tests/test_ids.py`).

## Phase 5 — Runtime Control ✅ (Phase 3에서 흡수)

`max_depth`, `max_iterations`, `max_children`, `token_budget`, `timeout` 전체 지원 —
세 primitive가 Runtime을 지나게 되면서(ADR-0008) 함께 완료됐다.

- 완료 기준: 각 한도를 위반하는 시나리오 테스트(`tests/test_runtime_control.py`,
  `tests/test_recursive.py`)가 존재하고, 모두 예외 폭발이 아닌 `budget_exceeded` 결과
  반환(지금까지의 마지막 답 포함)으로 종료된다. Custom Strategy가 한도를 몰라도 적용된다.
- Runtime 재사용 시 상태 초기화 규칙(ADR-0006 consequence)은 "`Agent.run`이 run마다 새 Runtime을
  만든다"로 해소 — 초기화 규칙 자체를 두지 않는다.

## Phase 6 — Execution & Events

Execution Tree 완성 + Event 시스템 (Trace, Logging, Token Usage, Cost).

먼저 **Event 없이 되는 것부터** 했다 — 로깅(stdlib `logging`)과 노드별 토큰
(`ExecutionNode.usage` / `subtree_usage()`). 관찰자가 하나면 Event는 필요 없다;
서로를 모르는 관찰자가 둘 이상 붙어야, 또는 로그를 **프로그램이 파싱**해야 할 때
비로소 Event가 값을 한다. 그 사람이 생기면 그때 만든다
(`examples/observability.py`, `tests/test_observability.py`).

- 완료 기준: [runtime.md](design/runtime.md#event-system)의 이벤트 전체가 발행되고,
  구독자 하나로 실행 전체의 토큰 사용량을 집계할 수 있다.

## Phase 6.5 — 실전 내구성 ✅

패턴을 늘리기 전에 기존 것이 실전에서 버티게 한다. 채택을 만드는 건 패턴 개수가 아니다.

- 스트리밍: `on_delta` 콜백 — 반환 계약을 바꾸지 않아 Strategy가 그대로다 (ADR-0012)
- Provider: `AnthropicProvider` 추가. Gemini/OpenRouter/vLLM은 `base_url`만 바꾼 같은 코드
- 재시도: SDK의 `max_retries`에 맡긴다 — 코어에서 또 재시도하면 백오프가 곱해진다
- 완료 기준: `tests/test_streaming.py`, `tests/test_anthropic_provider.py`, `examples/providers.py`

**남은 것 — 실제 엔드포인트 검증.** OpenAI와 Gemini는 실제 API로 확인했다(스트리밍·tool
왕복·usage). Claude·OpenRouter·vLLM은 코드와 단위 테스트만 있고 한 번도 호출하지 않았다
(Claude는 키는 있으나 크레딧 부족으로 400)
([검증 상태 표](design/abstractions.md#구현체--검증-상태를-함께-적는다)).
키가 확보되면 `uv run python examples/providers.py`로 확인한다 — 특히 usage가 새지 않는지.

**재시도의 남은 구멍.** 재시도를 다 쓰면 예외가 root까지 올라가 run이 죽는다.
부분 결과를 살리려면 Provider 오류를 `status='failed'` 계약으로 변환해야 한다
(협조적 취소와 같은 배관, ~10줄). 필요해질 때 한다.

## Phase 7 — Reflection

```text
Generate → Critique → Revision → Critique → Final
```

- 완료 기준: `examples/reflection.py` 동작.

## Phase 8 — Strategy Composition

```text
Recursive
 └── ReAct
      └── Reflection
```

- 완료 기준: `spawn_agent(strategy=...)` 로 child의 전략을 지정해 위 조합이 동작한다.

## Phase 9 — Plugin Architecture

Provider / Tool / Memory / Strategy를 외부 Package 형태로 추가.

- 완료 기준: 저장소 밖의 패키지에서 `register_*` 로 등록한 구성요소가
  코어 수정 없이 동작한다.
