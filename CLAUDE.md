# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

**Strata** — 다양한 Agentic Pattern(ReAct, Recursive/RLM, Reflection, …)을 하나의 Runtime 위에서
조합·실행하는 확장형 Agent Execution Framework. Python 3.12, 런타임 의존성 0개.

Phase 1~8 완료(6 제외) — ReAct / Recursive / RLM / Reflection Strategy, 전략 조합,
Runtime 한도 전체, Memory 3종, 멀티턴·취소·스트리밍·관찰. 남은 것은 Phase 6(Events)·
Phase 9(Plugin)이고 둘 다 소비자가 생길 때까지 미룬다.
구현 순서와 각 Phase의 완료 기준은 `docs/roadmap.md`를 따른다.

## 명령어

```bash
uv sync                              # 환경 생성 (Python 3.12, dev 그룹 포함)
uv run pytest                        # 전체 테스트
uv run pytest tests/test_smoke.py::test_agent_delegates_to_strategy   # 단일 테스트
uv run pre-commit run --all-files    # lint/포맷/타입 검사 전체 (커밋 시 자동 실행됨)
scripts/check_install.sh             # wheel 빌드 → 깨끗한 venv 설치 → 소비자 시나리오 검증
```

**검증은 반드시 저장소 안의 실행 가능한 파일(tests/, scripts/, examples/)로 만들어 실행한다.**
인라인 일회성 실행(heredoc, `python -c`)으로 검증을 끝내지 말 것 — 사용자가 같은 명령으로
재현할 수 있어야 한다.

## 아키텍처 — 지켜야 할 불변식

설계 전체는 `docs/`에 있다 (architecture → design → adr 순으로 읽기).
코드를 수정할 때 깨면 안 되는 규칙:

1. **Agent에는 실행 패턴 로직을 넣지 않는다.** Agent는 Provider/Strategy/Tools/Memory의
   조합만 담당하고 실행은 `Strategy.execute(context, runtime)`에 위임한다 (ADR-0003).
2. **Strategy는 Runtime primitive를 통해서만 리소스에 접근한다** —
   `runtime.generate()` / `runtime.execute_tool()` / `runtime.spawn_agent()` / `runtime.memory`.
   `runtime.provider.generate()` 직접 호출 금지(ADR-0008) — 한도·usage·이벤트가 `generate`에 걸려 있다.
   Strategy가 특정 Provider 구현을 import하면 설계 위반.
3. **Child Agent 생성은 반드시 `runtime.spawn_agent()` 경유** (ADR-0004).
   한도 검사(max_depth/max_children/token_budget)·Execution Tree 등록·이벤트 발행이
   전부 이 지점에서 일어난다. 한도 초과는 예외가 아니라 `status='budget_exceeded'` 반환.
   **Runtime 인스턴스는 run당 하나** — child는 parent의 Runtime을 공유하고,
   진입점은 `Agent.run(task)` 하나다 (ADR-0006).
   `run_id`(UUIDv7)는 Runtime이 발급하고 child가 공유한다 — **외부 id를 인자로 받지 않는다**(ADR-0011).
   취소도 한도와 같은 배관이다: `runtime.cancel()` → `Cancelled` 신호 → `run_strategy`가
   `status='cancelled'`로 변환(지금까지의 답 포함). 하드 취소(asyncio)는 전파하되 tree에 `cancelled`로 남긴다.
4. **Child → Parent에는 `AgentResult`(status/result/evidence/metadata) 계약만 전달** —
   child의 전체 Context를 넘기지 않는다 (재귀에서 context 폭발 방지).
5. **Context(현재 실행 상태) ≠ Conversation(멀티턴) ≠ Memory(실행 간 영속)** (ADR-0002/0010).
   흐름은 `Memory → retrieve → Context → Strategy` 단방향.
   대화 이력은 코어가 소유하지 않는다 — `Agent.run(task, history=...)`로 받고
   `result.metadata['messages']`로 돌려준다. 대화를 `Memory`에 쌓지 않는다(retrieve에 순서가 없다).
   transcript는 `Agent.run`에만 붙인다 — child의 `AgentResult`에 실으면 불변식 4가 깨진다.
6. I/O 경계(Provider, Tool, Memory, spawn)는 모두 `async def`.
   스트리밍은 `on_delta` 콜백이다 — `generate`의 반환은 여전히 완결된 `ModelResponse`이고
   Strategy는 스트리밍을 모른다(ADR-0012). `Agent.stream()` 같은 두 번째 진입점을 만들지 않는다.
   재시도는 SDK에 맡긴다(`max_retries`) — 코어에서 또 하면 백오프가 곱해진다.
   관찰은 stdlib `logging` — 라이브러리는 `NullHandler`만 달고 설정하지 않는다.
   모든 줄에 `run=`/`exec=`를 붙이고 `%s` 지연 포매팅을 쓴다(레벨이 꺼지면 비용 0).
   토큰은 `Runtime.usage`(총합)와 `ExecutionNode.usage`(노드별) 두 층이다.
7. **Tool은 `execute(self, env: ToolEnv, **kwargs)`** — Runtime에 닿는 유일한 길(ADR-0007).
   재귀의 트리거(`SpawnAgentTool`, `PythonTool.llm_query`)도 Tool이지만 메커니즘은 `env.runtime.spawn_agent()`.
8. system 지시는 `Context.instructions`(messages와 분리), 거대 입력은 `Context.variables['context']`
   (messages에 인라인 금지). `Runtime.generate`가 system을 조립하고, child는 지시를 상속·조각만 받는다.
   전략의 패턴 지시는 `Strategy.prompt`(고정 텍스트, `REACT/RECURSIVE/RLM_PROMPT`) + `environment()`(호출
   시점 상태)로 `instructions()`가 붙인다 — 변하는 것은 prompt에 구멍을 뚫지 말고 `environment()`로.
   모델 파라미터(temperature 등)는 코어가 해석하지 않는 dict이며 우선순위(Strategy > Provider 기본값)는
   `Runtime.generate`의 merge 한 줄에만 있다 — Provider 구현에서 다시 합치지 않는다.
   실행 한도도 같은 이음매다: 전략은 `Strategy.limits`로 **제안만** 하고(`ReflectionStrategy(rounds=4)`
   → `max_children=9`), 강제는 여전히 Runtime이며 우선순위(사용자 `RuntimeConfig` > `Strategy.limits`
   > 기본값)는 `Agent.run`의 `resolve_limits` 한 줄에만 있다 (ADR-0014). 한도를 Strategy로 옮기지 않는다 —
   Custom Strategy가 한도를 몰라도 걸리는 것이 확장점의 안전 속성이다.

설계가 바뀌는 변경은 해당 `docs/design/*.md`를 같은 커밋/PR에서 갱신하고,
되돌리기 비싼 결정은 `docs/adr/`에 새 ADR로 기록한다 (기존 ADR은 supersede, 삭제 금지).

## 코드 스타일

pre-commit이 강제한다 (`.pre-commit-config.yaml`): **작은따옴표** 문자열,
import 한 줄 단위 정렬 + `from __future__ import annotations` 자동 추가,
pyupgrade(py312), autopep8, flake8(`.flake8`, max-line 120), mypy.

- 식별자는 설계 문서의 영어 용어 그대로 (`spawn_agent`, `token_budget`). docstring·주석은 한국어.
- 테스트는 실제 LLM 호출 없이 — `tests/test_smoke.py`의 `FakeProvider`/`FakeStrategy` 패턴 재사용.

## Git

Git Flow: `main`(릴리스 태그만) ← `develop`(PR 대상) ← `feature/<kebab-case>`.
커밋은 Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
상세는 `docs/CONTRIBUTING.md`.
