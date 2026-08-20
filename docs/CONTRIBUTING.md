# Contributing Guide

개발 환경, 브랜치 전략, 코드 스타일 규칙.

## 개발 환경

- **Python 3.12** (`.python-version`으로 고정, `requires-python >= 3.12`)
- **[uv](https://docs.astral.sh/uv/)** 로 환경 관리

```bash
uv sync                        # .venv 생성 + 의존성 설치 (dev 그룹 포함)
uv run pre-commit install      # git hook 등록 (클론 후 1회)
uv run pytest                  # 테스트
uv run pre-commit run --all-files   # 전체 파일 lint/포맷 검사
uv run python examples/react.py     # ReAct end-to-end 예제
scripts/check_install.sh            # wheel 빌드 → 깨끗한 venv 설치 → 소비자 시나리오 검증
```

모든 검증은 위처럼 **저장소 안의 실행 가능한 파일**로 만든다 — 누구든 같은 명령으로
재현할 수 있어야 한다. 일회성 인라인 실행으로 검증을 끝내지 않는다.

### API 키 (.env)

통합 테스트·예제에 필요한 키는 `.env`로 관리한다:

```bash
cp .env.example .env    # 열어서 키 입력 (.env는 gitignore됨 — 절대 커밋 금지)
```

`tests/conftest.py`가 pytest 실행 시 `.env`를 자동 로드하므로 터미널·IDE 어디서든
동일하게 동작한다. 키가 없으면 통합 테스트는 실패가 아닌 skip으로 처리된다.
프레임워크 코어는 `.env`를 읽지 않는다 — dotenv는 dev 의존성일 뿐이다.

## 브랜치 전략 — Git Flow

```text
main ────────●──────────────●────────   릴리스만 (태그)
              \            /
develop ───────●──●──●──●──●─────────   통합 브랜치 (기본 작업 대상)
                \       /
feature/* ───────●──●──●─────────────   기능 단위 작업
```

| 브랜치 | 역할 | 규칙 |
|---|---|---|
| `main` | 릴리스 | 직접 커밋 금지. `develop`(또는 `hotfix/*`)에서만 머지, 머지 시 버전 태그 |
| `develop` | 통합 | 직접 커밋 금지. `feature/*` PR의 대상 브랜치 |
| `feature/<topic>` | 기능 작업 | `develop`에서 분기, 완료 시 `develop`으로 PR |
| `hotfix/<topic>` | 긴급 수정 | `main`에서 분기, `main`과 `develop` 양쪽에 머지 |

브랜치 이름은 kebab-case: `feature/react-strategy`, `feature/execution-tree`, `hotfix/token-count-overflow`.

### 작업 흐름 — feature 브랜치의 전체 수명주기

```bash
# 1. 시작: 항상 최신 develop에서 분기
git checkout develop
git pull                                  # 원격의 최신 상태 받기
git checkout -b feature/execution-tree    # 새 브랜치 생성 + 이동

# 2. 작업: 코딩 → 검증 → 커밋 (반복)
uv run pytest
uv run pre-commit run --all-files
git add -A
git commit -m "feat: ..."                 # 커밋 시 pre-commit 훅이 자동 실행됨

# 3. 머지: develop으로 돌아가서 --no-ff 머지
git checkout develop
git pull                                  # 그 사이 develop이 앞서갔을 수 있으니 다시 최신화
git merge --no-ff feature/execution-tree  # 머지 커밋을 남기는 gitflow 방식

# 4. 반영 + 정리
git push                                  # develop을 원격에 반영
git branch -d feature/execution-tree      # 로컬 브랜치 삭제
git push origin --delete feature/execution-tree   # 원격에도 푸시했었다면 원격 브랜치도 삭제
```

**`--no-ff`를 붙이는 이유**: 기본 머지(fast-forward)는 커밋을 develop에 일렬로 흡수해
브랜치 흔적이 사라진다. `--no-ff`는 머지 커밋을 강제로 만들어 "어디서 갈라졌고 어디서
합쳐졌는지"가 히스토리에 남는다 — 기능 단위 롤백(`git revert -m 1 <머지커밋>`)도 가능해진다.

```text
--no-ff (gitflow):                fast-forward (기본):
develop ──●─────────●── merge     develop ──●──●──●   ← 브랜치 흔적 없음
           \       /
            ●──●──●   feature
```

자주 하는 실수:
- **3단계에서 `git pull`을 빼먹음** → 다른 작업이 먼저 머지됐으면 push가 거부된다.
- **`-d`가 아닌 `-D`로 삭제** → `-d`는 머지 안 된 브랜치를 보호한다(에러 발생 시 머지 누락 신호).
  `-D`는 강제 삭제라 실수를 덮는다 — 항상 `-d` 먼저.
- **원격 브랜치 삭제 누락** → 로컬만 지우면 `origin/feature/*`가 계속 쌓인다.

머지 전 조건: `uv run pytest` / `uv run pre-commit run --all-files` 통과.

## 커밋 컨벤션 — Conventional Commits

```text
<type>: <제목 (명령형, 50자 이내)>

<본문 (선택): 무엇을, 왜>
```

| type | 용도 |
|---|---|
| `feat` | 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서만 변경 |
| `refactor` | 동작 변경 없는 구조 개선 |
| `test` | 테스트 추가·수정 |
| `chore` | 빌드, 설정, 의존성 등 |

예: `feat: ReActStrategy tool calling loop 구현`, `docs: ADR-0006 추가`.

## 코드 스타일

도구가 강제하는 것이 기준이다 — **pre-commit이 통과하면 스타일 논쟁은 끝**.
커밋 시 자동 실행되며, 스택은 `.pre-commit-config.yaml` 참조:

| 도구 | 역할 |
|---|---|
| flake8 | lint (`.flake8`: max-line-length 120) |
| autopep8 | PEP 8 자동 포맷 |
| double-quote-string-fixer | 문자열은 **작은따옴표** 통일 |
| reorder-python-imports | import 한 줄 단위 정렬 + `from __future__ import annotations` 자동 추가 |
| pyupgrade | 3.12 기준 최신 문법으로 재작성 |
| mypy | 타입 검사 (`pyproject.toml`의 `[tool.mypy]`) |
| pre-commit-hooks | trailing whitespace, EOF, YAML 검사, debug 문 검출, 테스트 파일명(`test_*.py`) |

도구가 못 잡는 규칙:

- **식별자는 영어** — 클래스·함수·변수는 설계 문서의 용어를 그대로 사용
  (`Provider`, `spawn_agent`, `token_budget`). docstring·주석은 한국어 가능.
- **공개 API에는 타입 힌트 필수** — base abstraction의 메서드 시그니처가 곧 계약이다.
  내부 helper는 자명하면 생략 가능.
- **abstraction 우선** — 구현체는 base 인터페이스에만 의존한다.
  Strategy가 특정 Provider를 import하면 설계 위반 ([project-overview](overview/project-overview.md)의 책임 분리).
- **docstring은 "왜"를 쓴다** — 코드가 보여주는 "무엇"을 반복하지 않는다.
  설계 결정을 참조할 때는 ADR 번호를 명시 (`ADR-0004`).
- **async 기본** — I/O 경계(Provider, Tool, Memory, spawn)는 모두 `async def`.

### 테스트

- pytest, `tests/` 아래에 `test_*.py`.
- 프레임워크 특성상 실제 LLM 호출 없이 테스트한다 — `tests/test_smoke.py`의
  `FakeProvider` / `FakeStrategy` 패턴을 재사용.
- 새 기능은 해당 동작이 깨지면 실패하는 테스트 최소 1개를 동반한다.

## 문서

- 설계가 바뀌는 변경은 해당 `docs/design/*.md` 갱신을 같은 PR에 포함한다.
- 새로운 설계 **결정**(되돌리기 비싼 선택)은 [ADR](adr/README.md)로 기록한다.
- 문서 언어는 한국어, 기술 용어·식별자는 원문 유지.
