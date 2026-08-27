# 변경 이력

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/), 버전은
[Semantic Versioning](https://semver.org/lang/ko/)을 따른다.

**0.x 동안 minor 버전은 호환을 깰 수 있다.** `1.0`은 실사용자가 생기고 API가 몇 달간
안정된 뒤에 붙인다 — "완성했다"가 아니라 "이제 못 바꾼다"는 선언이기 때문이다.

## [0.1.0] — 2026-08-27

첫 릴리스. 조립(Provider·Tool·Memory 등록)만으로 실행 패턴을 쓸 수 있고, 어느 패턴이
맞는지도 라우터가 고른다. **런타임 의존성 0개**, Python 3.12+.

### Agent · Runtime

- `Agent(provider, strategy, tools, memory, instructions, config, on_delta)` — 조합만 담당하고
  실행은 Strategy에 위임한다. 진입점은 `Agent.run(task, context=, history=)` 하나다.
- 리소스는 Runtime primitive를 통해서만 닿는다 — `generate` / `execute_tool` / `spawn_agent` /
  `memory` / `execution`. 한도 검사·토큰 집계·경고가 전부 이 지점에 걸려 있어
  **커스텀 전략이 한도를 몰라도 막힌다.**
- 한도 전체: `max_depth` / `max_iterations` / `max_children` / `token_budget` / `timeout`.
  초과는 예외가 아니라 `status='budget_exceeded'` + **지금까지의 답**으로 돌아온다.
- 전략이 한도를 *제안*할 수 있다(`Strategy.limits`). 우선순위는 사용자 `RuntimeConfig` >
  전략 > 기본값이고, 파생된 한도는 하한으로만 쓰인다(올리기만 하고 내리지 않는다).
- `run_id`(UUIDv7)를 코어가 발급한다. 외부 id를 인자로 받지 않는다.
- 취소 두 종류: 협조적(`runtime.cancel()` — 지금까지의 답을 살린다)과 하드(`asyncio`).

### Strategy — 5종

| | |
|---|---|
| `ReActStrategy` | tool calling loop. 기본 |
| `RecursiveStrategy` | ReAct + `spawn_agent` — 하위 과제를 깨끗한 문맥의 child에 위임 |
| `RLMStrategy` | ReAct + 파이썬 REPL + `llm_query` — 한 윈도우에 안 들어가는 입력 |
| `ReflectionStrategy` | 초안 → 비판 → 수정. 라운드 고정, 조기 종료 없음 |
| `RouterStrategy` | 어느 전략이 맞는지 고르고 그것이 끝까지 푼다 |

- 패턴 지시는 `Strategy.prompt`(고정 텍스트) + `environment()`(호출 시점 상태). 내보낸
  상수(`REACT_PROMPT` 등)가 곧 모델이 보는 텍스트다.
- 덮어쓰기는 전부 명시 인자다 — `prompt=`, `model_params=`, `description=`, 그리고 한도.
- 라우터는 결정적 규칙이 모델보다 먼저다(거대 입력 → RLM, 모델 호출 0회). 분류는
  free-text가 아니라 `route(strategy: enum)` tool call 1회이고, 실패하면 `default`.
- 라우터는 고른 전략을 **같은 Context에서** 실행한다 — child로 띄우면 대화 이력을 잃어
  멀티턴이 깨지기 때문이다.

### Provider — 4종

- `OpenAIProvider` / `AnthropicProvider` / `GeminiProvider`(네이티브 SDK) / `FallbackProvider`.
- vLLM·Ollama·OpenRouter는 별도 클래스가 아니라 `base_url`만 바꾼 같은 코드다.
- 스트리밍은 `on_delta` 콜백이다 — 반환은 여전히 완결된 `ModelResponse`이고 Strategy는
  스트리밍을 모른다. 두 번째 진입점을 만들지 않았다.
- 재시도는 SDK의 `max_retries`에 맡긴다. 코어에서 또 하면 백오프가 곱해진다.
- SDK 예외는 `ProviderError`로 번역되어 `status='failed'` + 지금까지의 답으로 끝난다.
  프로그래밍 오류는 그대로 전파된다.
- 벤더 전용 상태는 `ToolCall.provider_state`로 왕복시킨다(Gemini 3.x `thought_signature` 등).

### Memory — 3종

- `InMemory` / `SQLiteMemory`(stdlib) / `RedisMemory`(클라이언트 주입) — 런타임 의존성 0 유지.
- 조회는 `Agent.run`이 자동으로, 저장은 모델이 `MemoryTool`로 명시적으로. 저장을 아끼는 것이
  검색 품질을 지키는 방법이다.
- 스코프는 인자가 아니라 인스턴스가 가른다(`namespace=`).
- 관련성은 BM25 하나로 세 구현이 공유한다. 토큰이 아니라 부분 문자열로 세는데, 한국어가
  교착어라 단어 단위 비교가 거의 다 빗나가기 때문이다.

### 멀티턴

- 대화 이력은 코어가 소유하지 않는다 — `Agent.run(task, history=...)`로 받고
  `result.metadata['messages']`로 돌려준다. `Agent`가 무상태라 멀티 워커에서 그대로 돈다.
- `messages`는 순수 JSON이다(`tool_calls`도 dict). 앱의 DB·큐를 그대로 왕복한다.
- `trim_history(messages, keep_turns)` — 턴 경계에서만 자른다. 순진한 슬라이스는 tool 왕복
  쌍을 깨서 프로바이더가 400을 낸다.

### 관찰

- stdlib `logging`. 라이브러리는 `NullHandler`만 달고 설정하지 않는다. 모든 줄에
  `run=`/`exec=`가 붙는다.
- 토큰은 두 층 — `Runtime.usage`(총합)와 `ExecutionNode.usage`(노드별) + `subtree_usage()`.
- 모델이 tool call을 텍스트로 흘리면 경고한다(`model.tool_call_may_have_leaked_as_text`).
  조용한 실패를 보이는 실패로 바꾼다.

### 도구

- `scripts/selfcheck.py` — `CLAUDE.md`·`AGENTS.md`의 규칙을 코드가 지키는지 실제 모델로 감사한다.
  `--repo`/`--rules`로 아무 저장소나 겨눌 수 있고, `--planted`가 감사기에 신호가 있는지 확인한다.
- `scripts/check_install.sh` — wheel 빌드 → 깨끗한 venv 설치 → 예제 실행.

### 문서

- `docs/guide/` 8편(사용) · `docs/design/`(설계 근거) · `docs/adr/` 15편(결정 기록).
- `make docs` — docstring에서 API 레퍼런스 생성. 파라미터 목록은 손으로 쓰지 않는다.

### 알려진 한계

- **`PythonTool`은 샌드박스가 아니다.** 모델 코드가 이 프로세스 권한으로 실행된다.
  신뢰된 환경 전용이며, 격리는 같은 `name='python'`으로 교체한다(ADR-0015).
- Memory 조회는 전체 스캔이고 의미 검색이 아니며 시간 개념이 없다.
- Event 시스템(Phase 6)은 없다. 관찰자가 둘 이상 생기면 만든다.
- 실제 엔드포인트 검증: OpenAI·Gemini·vLLM은 스트리밍·tool 왕복·usage까지 확인.
  Claude·OpenRouter·Ollama는 미검증.
- 대화가 컨텍스트를 넘길 때의 `400`이 일시적 인프라 오류와 같은 칸으로 분류된다 —
  `FallbackProvider`가 헛돈다.

[0.1.0]: https://github.com/IamMcCoy/strata/releases/tag/v0.1.0
