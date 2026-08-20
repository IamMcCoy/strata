# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

**Strata** — 다양한 Agentic Pattern(ReAct, Recursive/RLM, Reflection, …)을 하나의 Runtime 위에서
조합·실행하는 확장형 Agent Execution Framework. Python 3.12, 런타임 의존성 0개.

현재 **Phase 1 (Core Abstraction)** 단계: `src/strata/`에는 인터페이스 뼈대만 있고 실행 로직이 없다.
`Runtime`의 `NotImplementedError`는 의도된 것 — 구현 순서와 각 Phase의 완료 기준은
`docs/roadmap.md`를 따른다.

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
   `runtime.provider` / `runtime.tools` / `runtime.memory` / `runtime.spawn_agent()`.
   Strategy가 특정 Provider 구현을 import하면 설계 위반.
3. **Child Agent 생성은 반드시 `runtime.spawn_agent()` 경유** (ADR-0004).
   한도 검사(max_depth/max_children/token_budget)·Execution Tree 등록·이벤트 발행이
   전부 이 지점에서 일어난다. 한도 초과는 예외가 아니라 `status='budget_exceeded'` 반환.
   **Runtime 인스턴스는 run당 하나** — child는 parent의 Runtime을 공유하고,
   진입점은 `Agent.run(task)` 하나다 (ADR-0006).
4. **Child → Parent에는 `AgentResult`(status/result/evidence/metadata) 계약만 전달** —
   child의 전체 Context를 넘기지 않는다 (재귀에서 context 폭발 방지).
5. **Context(현재 실행 상태) ≠ Memory(실행 간 영속)** (ADR-0002).
   흐름은 `Memory → retrieve → Context → Strategy` 단방향.
6. I/O 경계(Provider, Tool, Memory, spawn)는 모두 `async def`.

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
