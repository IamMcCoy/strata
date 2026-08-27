# Strata

> A composable runtime for agentic systems.

**Strata**는 다양한 Agentic Pattern(ReAct, Recursive/RLM, Reflection, …)을
하나의 Runtime 위에서 구현하고 조합할 수 있도록 하는 확장형 Agent Execution Framework다.
Provider, Tool, Memory, Context, Strategy, Execution을 독립적인 primitive로 추상화하고,
Runtime이 이들을 연결·실행·관찰한다.

**런타임 의존성 0개.** Provider SDK는 선택적으로 설치한다 — 그래서 앱이 고정한
`openai`/`anthropic` 버전과 절대 충돌하지 않는다.

```python
from strata import Agent, OpenAIProvider, RLMStrategy, RuntimeConfig

agent = Agent(
    provider=OpenAIProvider(model='gpt-4o-mini', model_params={'temperature': 0.3}),
    strategy=RLMStrategy(),             # ReActStrategy / RecursiveStrategy 로 교체 가능
    instructions='한국어로 간결하게 답하라.',   # system 지시 — child가 상속한다
    config=RuntimeConfig(max_depth=3, token_budget=200_000),
)

# 거대 입력은 메시지가 아니라 변수 `context`로 들어간다 — 모델은 python tool로 조각내고
# llm_query로 child agent에 조각만 넘겨 결과를 모은다 (RLM).
result = await agent.run('이 문서의 모든 장의 핵심 숫자를 합산하라.', context=huge_document)
print(result.status, result.result)   # completed | failed | budget_exceeded | cancelled
```

같은 Agent에서 `strategy=`만 교체하면 실행 패턴이 바뀐다. 한도(depth/children/iterations/
token/timeout)는 Strategy가 아니라 **Runtime이** 강제하므로 Custom Strategy가 한도를 몰라도
지켜지고, 초과 시 예외 대신 `budget_exceeded` 결과(지금까지의 답 포함)를 돌려준다.

## 구성요소

### Provider

| | 쓰는 법 | 실제 API 검증 |
|---|---|---|
| OpenAI | `OpenAIProvider(model='gpt-4o-mini')` | ✅ 스트리밍·tool·usage |
| Gemini | `GeminiProvider(model='gemini-3.5-flash-lite')` | ✅ 스트리밍·tool·usage |
| vLLM | `OpenAIProvider(base_url='http://host:port/v1')` | ✅ 스트리밍·usage <sup>1</sup> |
| Claude | `AnthropicProvider(model='claude-sonnet-5')` | ❌ 미검증 |
| OpenRouter | `OpenAIProvider(base_url='https://openrouter.ai/api/v1')` | ❌ 미검증 |
| Ollama | `OpenAIProvider(base_url='http://localhost:11434/v1')` | ❌ 미검증 |

<sup>1</sup> vLLM에서 tool을 쓰려면 서버가 `--enable-auto-tool-choice`로 떠 있어야 한다.

OpenAI-compatible 엔드포인트는 `base_url`만 바꾼 **같은 코드**다. 별도 구현이 필요한 건
Claude와 Gemini뿐 — 둘 다 메시지 형식이 근본적으로 다르다.
재시도는 SDK에 맡긴다: `Provider(..., max_retries=2, timeout=30)`.

### Memory — 실행 간 영속 (Context와 분리, [ADR-0002](docs/adr/0002-context-memory-separation.md))

| | 언제 | 비용 |
|---|---|---|
| `InMemory()` | 개발·테스트·단일 프로세스 | 없음 |
| `SQLiteMemory('mem.db')` | 영속 + 멀티 워커(같은 호스트) | stdlib `sqlite3` |
| `RedisMemory(client)` | 워커가 여러 호스트에 흩어질 때 | 클라이언트를 **주입**받는다 |

`retrieve`는 `Agent.run`이 자동으로(→ system 지시), `store`는 모델이 `MemoryTool`로 명시적으로.
스코프는 인스턴스가 가른다: `SQLiteMemory(path, namespace=f'user:{uid}')`.

### Strategy

`ReActStrategy` / `RecursiveStrategy` / `RLMStrategy` / `ReflectionStrategy` / `RouterStrategy`.
각 Strategy는 자기 패턴의 harness prompt(tool 규율·종료 규약·위임 규칙)를 갖고
system = `instructions` + `prompt` + 현재 상태로 조립한다. Tool은 `execute(self, env, **kwargs)`
하나만 구현한다.

`RouterStrategy`는 과제에 맞는 전략을 고르고 그것이 끝까지 풀게 한다 — 거대 입력이 오면
묻지 않고 RLM으로 가고(사실이지 판단이 아니다), 아니면 `route(strategy: enum)` tool call 1회로
정한다. 고른 전략을 **같은 Context에서** 실행하므로 라우터를 씌워도 멀티턴이 깨지지 않는다.
판단 근거는 각 전략의 `description`이고, 도메인 용어로 덮어쓰는 것이 가장 값싼 튜닝이다:

```python
RouterStrategy({
    'lookup': ReActStrategy(description='단순 조회·계산. 사내 API로 바로 답할 수 있는 질문.'),
    'bulk':   RLMStrategy(description='대용량 로그·문서 일괄 처리.'),
}, default='lookup')
```

`ReflectionStrategy`는 초안·비판·수정을 전부 child로 띄우는 오케스트레이터라
스스로 `generate`를 부르지 않는다 — child가 parent 대화를 못 본다는 불변식이 그대로
"자기 초안에 물들지 않은 비판자"가 된다. 전략 조합은 `worker=`로 한다:
`ReflectionStrategy(rounds=2, worker=RecursiveStrategy())`.

> ⚠️ **`RLMStrategy`의 `PythonTool`은 샌드박스가 아니다.** 모델이 만든 코드가 이 프로세스
> 권한으로 실행된다 — 파일·네트워크·환경변수 전부. **신뢰된 환경 전용**이다.
> 최종 사용자 입력이 프롬프트에 닿는다면 같은 `name='python'`으로 격리 구현(컨테이너·원격 커널)을
> 만들어 `tools=[...]`에 등록하라 — registry가 전략의 기본 tool을 이긴다.
> 코어가 인프로세스 샌드박스를 만들지 않는 이유는
> [ADR-0015](docs/adr/0015-no-in-process-sandbox.md).

## 주요 기능

### 스트리밍 — 콜백이지 두 번째 진입점이 아니다 ([ADR-0012](docs/adr/0012-streaming-as-a-side-channel.md))

```python
agent = Agent(..., on_delta=lambda text, execution_id: queue.put_nowait(text))
```
`generate`의 반환은 스트리밍 여부와 무관하게 **완결된 `ModelResponse`**다. 그래서 Strategy는
스트리밍을 모르고, 한도·usage 집계가 한 경로로 유지된다. 재귀에서는 `execution_id`로
어느 child가 말하는지 갈린다.

### 멀티턴 — 대화 이력은 코어가 소유하지 않는다 ([ADR-0010](docs/adr/0010-conversation-history-is-not-core-state.md))

```python
history = db.load(session_id)
result = await agent.run(task, history=history)
db.save(session_id, result.metadata['messages'])
```
`Agent.run`이 무상태로 남아 멀티 워커에서 그대로 동작한다.
`Context`(한 run) ≠ `Conversation`(run 사이) ≠ `Memory`(영속되는 사실) — 셋은 다른 것이다.

### 취소 — 두 종류 ([ADR-0011](docs/adr/0011-run-id-and-two-kinds-of-cancellation.md))

| | 방법 | 부분 결과 |
|---|---|---|
| 하드 | `asyncio.Task.cancel()` | 없음 |
| 협조적 | `runtime.cancel(reason)` | **지금까지의 답을 살린다** |

협조적 취소는 Provider 호출 **앞**에서 멈추므로 취소 후 LLM 비용이 0이다.

### 오류 — 인프라와 프로그래밍을 가른다 ([ADR-0013](docs/adr/0013-provider-errors-become-a-result-contract.md))

| | 결말 |
|---|---|
| 429·5xx·타임아웃 (재시도 소진 후) | `status='failed'` + **지금까지의 답을 살린다** |
| `TypeError` 등 내 코드 버그 | 그대로 터진다 — 삼키지 않는다 |

30분짜리 재귀가 마지막 호출의 rate limit으로 통째로 날아가지 않는다.
폴백이 필요하면 `Agent(provider=FallbackProvider([openai, claude]), ...)`.

### 관찰 — stdlib `logging`

```python
logging.basicConfig(level=logging.DEBUG)      # 라이브러리는 NullHandler만 단다
```
```text
run=01a03c7b-… exec=exec_0 agent.started task=루트 작업
run=01a03c7b-… exec=exec_2 agent.spawned parent=exec_0 depth=1 task=비싼 조각
run=01a03c7b-… exec=exec_0 agent.finished status=completed tokens=115
```
`run_id`(UUIDv7, 코어가 발급)로 프로세스를 넘어 줄을 묶는다. 토큰은 두 층이다 —
`Runtime.usage`(run 총합)와 `ExecutionNode.usage`/`subtree_usage()`(노드별, 재귀에서
어느 가지가 비쌌는지).

## 설치

아직 PyPI에 배포하지 않았다 (배포명·라이선스 미정). git으로 직접 설치:

```bash
uv add git+https://github.com/IamMcCoy/strata.git
```

코어는 의존성 0개다. 쓰는 SDK만 extra로 고른다:

```bash
uv add 'strata[openai] @ git+https://github.com/IamMcCoy/strata.git'
# anthropic / gemini / redis / all
```

타입 힌트가 포함되어 있다(PEP 561, `py.typed`).

## 예제

```bash
uv run python examples/react.py           # fake provider — 키 없이 동작
uv run python examples/recursive.py       # 재귀 + Execution Tree
uv run python examples/rlm.py             # 거대 입력을 변수로 다루기
uv run python examples/memory.py          # 실행 간 기억
uv run python examples/conversation.py    # 멀티턴 + Memory 층
uv run python examples/observability.py   # 로그 + 노드별 토큰

uv run python examples/providers.py       # 실제 API — 키가 있는 Provider만 호출
make redis-up && uv run python examples/worker.py   # Redis 큐 + 워커 2프로세스
```

## 문서

- [문서 인덱스](docs/README.md) — 읽는 순서 안내
- [아키텍처](docs/architecture/architecture.md) · [설계](docs/design/abstractions.md)
- [ADR](docs/adr/README.md) — 되돌리기 비싼 결정과 그 근거 12건
- **[사용 가이드](docs/guide/)** — 조립·프로바이더·도구·기억·멀티턴·전략·한도
- [로드맵](docs/roadmap.md) · [기여 가이드](docs/CONTRIBUTING.md)

## 상태

Phase 1~8 완료(6 제외) — ReAct/Recursive/RLM/Reflection/Router Strategy, 전략 조합,
Runtime 한도 전체, Memory 3종, 멀티턴, 취소, 스트리밍, Provider 4종, 로깅·노드별 토큰.
남은 것은 Phase 6(Events)·Phase 9(Plugin) — 둘 다 소비자가 생길 때까지 미룬다.
상세는 [로드맵](docs/roadmap.md).

## 개발 환경

Python 3.12 + [uv](https://docs.astral.sh/uv/).

```bash
make install            # uv sync
make test               # 단위 테스트 — 외부 의존 0, 네트워크로 나가지 않는다
make lint               # pre-commit 전체
make check              # lint + test (커밋 전)
make test-integration   # 실제 Redis + 멀티프로세스 (docker 필요)
make test-providers     # 실제 엔드포인트 — base_url이 없으면 유료 API로 나간다
make help               # 전체 명령
```

통합 테스트는 `integration` 마커로 기본 실행에서 빠져 있다. `make test`는 API 키가
환경에 있어도 밖으로 나가지 않는다 — 전부 돌리려면 `uv run pytest -m integration`.

브랜치 전략과 코드 스타일은 [기여 가이드](docs/CONTRIBUTING.md) 참조.
