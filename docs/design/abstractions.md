# Core Abstractions

Phase 1에서 확립하는 핵심 인터페이스. **구현보다 abstraction 설계를 우선한다.**
Strategy는 별도 문서([strategies.md](strategies.md)), Runtime/Execution/Event는
[runtime.md](runtime.md) 참조.

## Provider

LLM과의 통신을 추상화한다. Strategy나 Agent는 특정 Provider의 API를 직접 호출하지 않는다.

```python
class Provider(ABC):

    async def generate(
        self,
        messages,
        tools=None,
        **kwargs,
    ) -> ModelResponse:
        ...
```

```text
Strategy
    ↓
Provider Interface
    ↓
OpenAI / Anthropic / vLLM / Custom
```

**동일한 Strategy를 여러 Provider에서 실행할 수 있어야 한다.** 지원 대상:
OpenAI, Anthropic, Google, vLLM, Ollama, OpenAI-compatible API, Local Model, Custom.

```python
provider = OpenAIProvider(model="gpt-5.6")
# 또는
provider = VLLMProvider(base_url="http://localhost:8000/v1", model="qwen")
```

`ModelResponse`는 Provider별 응답 형식을 통일하는 값 객체다.

- `text` — 텍스트 출력
- `tool_calls: list[ToolCall]` — 모델의 tool 호출 요청.
  **Provider가 자사 형식을 `ToolCall(name, arguments)`로 통일**하므로 Strategy는 파싱을 모른다.
- `usage` — 토큰 사용량. **표준 키 `input_tokens` / `output_tokens` / `total_tokens`로
  변환하는 책임은 Provider에 있다** — Runtime의 token budget
  집계([runtime.md](runtime.md#execution-control))가 이 키를 전제한다.

`Tool.input_schema`(JSON Schema)를 각 Provider의 tool 형식으로 변환하는 책임도
Provider에 있다 — Strategy와 Tool은 Provider별 형식을 모른다.

### 모델 파라미터 (temperature 등)

샘플링 파라미터는 코어가 해석하지 않는 **불투명 dict**다 — Provider마다 지원 키가 다르고
(`top_k`는 Anthropic만, reasoning 모델은 `temperature` 거부) 코어는 모델 중립을 유지한다.
`generate(**kwargs)`가 Runtime을 거쳐 Provider 요청에 그대로 실린다. 입구는 두 층:

```python
OpenAIProvider(model, model_params={'temperature': 0.2})   # 배포 기본값 — 이 Provider의 모든 요청
ReActStrategy(model_params={'temperature': 0})             # 패턴별 값 — 이 Strategy의 모든 generate
```

우선순위는 **Strategy > Provider 기본값**이고, 합치는 곳은 `Runtime.generate` 한 줄뿐이다 —
`provider.generate(messages, tools, **{**provider.model_params, **kwargs})`. `Provider` 베이스가
`model_params`를 가지므로 구현(OpenAI, 향후 Anthropic 등)은 받은 kwargs를 요청에 그대로 실으면
된다. child는 Strategy
인스턴스를 상속하므로 같은 값을 쓰고, Router/Reflection처럼 "분류는 temp 0, 생성은 0.7"이 필요한
패턴은 Strategy 인스턴스마다 다른 값을 준다. `RuntimeConfig`에는 두지 않는다 — 거긴 Runtime이
*강제*하는 한도만 ([runtime.md](runtime.md#execution-control)).

### API Key와 의존성

- 키 우선순위: **명시적 인자 > Provider별 관례 환경변수**
  (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).
- 프레임워크는 키를 저장·로깅하지 않고 SDK에 전달만 한다.
  `.env` 로딩도 프레임워크가 하지 않는다 — 앱의 몫이며 `.env`는 gitignore된다.
- Provider SDK는 **optional extras**로 설치한다 (`uv add 'strata[openai]'`) —
  코어는 의존성 0을 유지하고, SDK import는 Provider 생성 시점에 일어나므로
  extras 없이도 `import strata`는 동작한다.

### 스트리밍 — 부수 채널 (ADR-0012)

```python
async def generate(self, messages, tools=None, on_delta=None, **kwargs) -> ModelResponse
```

`on_delta`를 줘도 **반환은 완결된 `ModelResponse`다.** 그래서 Strategy는 스트리밍을 몰라도
되고 한도·usage 집계가 한 경로로 유지된다. 앱이 보는 시그니처는 `on_delta(text, execution_id)` —
`execution_id`는 Runtime이 붙인다(Provider는 실행 트리를 모른다).

```python
Agent(provider=..., strategy=..., on_delta=lambda text, execution_id: queue.put_nowait(text))
```

동기 콜백이다: `await`하면 실행이 소비자 속도에 묶인다. 구독자 예외는 삼킨다.

### 구현체 — 검증 상태를 함께 적는다

| | 방법 | 실제 엔드포인트 검증 |
|---|---|---|
| OpenAI | `OpenAIProvider(model=...)` | ✅ 스트리밍·tool 왕복까지 확인 |
| Claude | `AnthropicProvider(model=...)` — 메시지 형식이 달라 별도 구현 | ❌ **미검증** (변환 단위 테스트만) |
| vLLM | `OpenAIProvider(base_url='http://host:port/v1')` | ✅ 스트리밍·usage 확인 (주의사항 아래) |
| Ollama | `OpenAIProvider(base_url='http://localhost:11434/v1')` | ❌ **미검증** |
| OpenRouter | `OpenAIProvider(base_url='https://openrouter.ai/api/v1')` | ❌ **미검증** |
| Gemini | `GeminiProvider(model=...)` — 네이티브 SDK, 별도 구현 | ✅ 스트리밍·tool 왕복·usage 확인 |
| Gemini (호환 경로) | `OpenAIProvider(base_url='https://generativelanguage.googleapis.com/v1beta/openai/')` | ❌ **미검증** |

**미검증이 뜻하는 것**: 코드는 있고 단위 테스트도 있지만 실제 API로 한 번도 호출하지
않았다. 특히 확인이 필요한 지점은 **OpenAI 호환 계층이 `stream_options: {include_usage: true}`를
받는가**다 — 안 받으면 usage가 0으로 새고 `token_budget`이 무의미해진다.

실제 호출로만 드러난 문제가 이 프로젝트에서 이미 셋이다: 스트림 미close로 인한 커넥션 누수,
redis.asyncio의 이벤트 루프 바인딩, 그리고 **Gemini 3.x의 `thought_signature` 왕복 요구**
(없으면 tool이 아예 동작하지 않는데 fake 테스트는 전부 통과했다).

### vLLM 주의사항 (실측)

`Gemma4-E2B-it` 기준으로 확인한 것:

- **usage는 정상이다.** `stream_options: {include_usage: true}`를 받는다 —
  스트리밍에서도 `token_budget`이 동작한다.
- **tool을 쓰려면 서버 플래그가 필요하다.** `--enable-auto-tool-choice`와
  `--tool-call-parser` 없이 뜬 서버에 tool을 넘기면 400으로 거절한다.
  코드 문제가 아니라 서버 기동 옵션이다.
- 스트리밍 시 `httpcore2`의 async generator 정리 경고가 출력될 수 있다.
  **결과·usage는 정상**이며 같은 코드가 OpenAI에서는 조용하다 —
  vLLM의 SSE 종료 방식과 HTTP 스택 사이의 상호작용으로 보인다. 명시적 client close로도
  사라지지 않아 추적을 중단했다.

### 벤더 전용 상태 — `ToolCall.provider_state`

코어가 해석하지 않고 그대로 왕복시키는 불투명 주머니다. 벤더 필드를 `ToolCall` 본문에
넣으면 계약이 오염되고, 버리면 해당 벤더에서 tool이 깨진다.
`messages`에 실려 앱의 저장소를 왕복하므로 **JSON 직렬화 가능한 값만** 넣는다(ADR-0010) —
Gemini의 `thought_signature`는 bytes라 base64로 옮긴다.

**Gemini에 네이티브 구현을 둔 이유**: OpenAI 호환 계층은 shim이라 네이티브 기능(thinking 등)을
못 쓰고 `stream_options` 지원이 버전에 따라 갈린다. 다만 `client.interactions`(next-gen API)는
쓰지 않는다 — 그건 `agents`/`environments`/`webhooks`와 함께 있는 **구글의 agent 실행 API**로
strata와 같은 층의 추상화라, Provider로 감싸면 Runtime의 한도·usage·재귀 제어가 이중으로 겹친다.
Provider가 필요로 하는 무상태 완성 호출은 `generate_content`다.

재시도는 SDK에 맡긴다: `Provider(..., max_retries=2, timeout=30)` — 명시 인자이며 기본값 2다.
Gemini SDK는 재시도 횟수가 아니라 **총 시도 횟수**(`attempts`)를 받으므로 `+1`로 변환한다 —
안 그러면 같은 값이 벤더마다 다르게 동작한다.
코어에서 또 재시도하면 백오프가 곱해진다. 총 대기 시간은 대략 `max_retries × timeout` (ADR-0012).

## Tool

Agent가 외부 시스템·환경과 상호작용하기 위한 abstraction.
Provider나 Strategy에 종속되지 않는다.

```python
class Tool(ABC):

    name: str
    description: str
    input_schema: dict          # JSON Schema — Provider가 자사 형식으로 변환

    async def execute(self, env: ToolEnv, **kwargs):
        ...


@dataclass
class ToolEnv:
    context: Context            # 호출한 agent의 Context
    runtime: Runtime            # run의 Runtime
```

첫 인자 `env`는 **항상** 전달된다 ([ADR-0007](../adr/0007-spawn-trigger-is-a-tool.md)).
대부분의 Tool은 무시한다. Runtime primitive가 필요한 Tool — `SpawnAgentTool`(`env.runtime.spawn_agent`),
`PythonTool`(`env.context.variables`를 REPL 네임스페이스로, `llm_query` → spawn) — 만 사용한다.
Tool이 Runtime에 닿는 길이 이것 하나이므로, Tool에서 시작하는 재귀도 한도·Tree의 통제 안이다.

예: `WebSearchTool`, `PythonTool`, `DatabaseTool`, `FileTool`, `HTTPTool`,
`MCPTool`, `CustomTool`. Tool 예외·unknown tool은 `runtime.execute_tool`이 관찰 문자열로 바꾼다.

## Memory

현재 실행을 넘어 정보를 저장하고 재사용하기 위한 abstraction.
Context와의 분리는 [ADR-0002](../adr/0002-context-memory-separation.md) 참조.

```python
class Memory(ABC):

    async def store(self, item: MemoryItem): ...

    async def retrieve(self, query: str, limit: int = 10): ...

    async def delete(self, memory_id: str): ...
```

### 구현체 — 코어가 소유하는 셋

관련성 판단(`rank()`)은 `memory/base.py` 한 곳에 있고 세 구현이 공유한다 — 저장소가 달라도
"무엇이 관련 있는가"는 하나여야 하기 때문이다. 부분 문자열 겹침으로 세는 이유는 한국어가
교착어라 단어 단위 비교('uv를' != 'uv')가 거의 다 빗나가서다.

| 구현 | 언제 | 비용 |
|---|---|---|
| `InMemory` | 개발·테스트·단일 프로세스 | 없음 |
| `SQLiteMemory` | 영속 + 멀티 워커(같은 호스트) | stdlib `sqlite3` — 의존성 0개 유지 |
| `RedisMemory` | 워커가 여러 호스트에 흩어질 때 | 클라이언트를 **주입**받는다 — strata는 `redis`를 import하지 않는다 |

`RedisMemory(client, namespace=...)`가 주소가 아니라 **클라이언트**를 받는 이유:
`dependencies = []`를 지키고, 연결 풀·재연결·타임아웃 정책을 코어가 아니라 애플리케이션에 남긴다.
`hset`/`hgetall`/`hdel`을 await할 수 있으면 어떤 클라이언트든 된다.
주소만 있을 때는 `RedisMemory.from_url('redis://...')` — `redis`를 메서드 안에서 지연 import하므로
의존성 0개는 그대로다(`test_importing_strata_does_not_import_redis`가 지킨다).

스코프를 나눌 때 `from_url`을 반복 호출하면 사용자 수만큼 커넥션 풀이 생긴다.
**클라이언트는 공유하고 인스턴스만 나눈다** — 그게 주입 설계가 주는 것이다.
redis.asyncio 클라이언트는 자기를 만든 이벤트 루프에 묶이므로 프로세스/루프당 하나를 재사용한다.

**스코프는 인스턴스가 가른다** — `retrieve`에 필터 인자를 두지 않는다.
사용자·세션별 격리는 `SQLiteMemory(path, namespace=f'user:{uid}')`처럼 인스턴스를 나눠서 한다.
메서드 인자로 두면 모든 구현이 필터링을 구현해야 하고 호출자가 매번 넘겨야 한다.

MariaDB·PostgreSQL·Vector DB는 코어가 소유하지 않는다. SQL 방언은 플레이스홀더(`?`/`%s`/`$1`)부터
전문검색(`FTS5`/`MATCH…AGAINST`/`tsvector`)까지 달라 "공통 SQLMemory"는 전체 스캔으로만 수렴하고,
묶으려면 SQLAlchemy가 필요해 의존성 0개가 깨진다. `Memory` ABC가 이미 그 추상화이므로
각 DB는 40줄짜리 `Memory` 구현을 직접 쓰면 된다 — 그 아래 두 번째 추상화 계층을 두지 않는다.

### Lifecycle — 흐름은 단방향 (ADR-0002)

| 방향 | 누가 | 어디서 |
|---|---|---|
| retrieve | 자동 | `Agent.run`이 task로 조회해 사용자 지시 뒤에 붙인다 (`Context.instructions` → system, child도 상속) |
| store | 명시적 | 모델이 `MemoryTool`(`remember`)을 호출한다. 트리거는 Tool, 메커니즘은 `env.runtime.memory` (ADR-0007) |

Strategy는 retrieve를 직접 부르지 않는다 — 이미 Context에 주입된 상태로 받는다.
자동 store는 두지 않는다: 무엇을 남길지는 코어가 아니라 모델의 판단이다.

### Memory Type

장기적으로 지원할 개념적 분류:

| 타입 | 저장 대상 | 예 |
|---|---|---|
| Working | 현재 작업 상태 | (초기에는 Context가 담당 — 역할이 겹침) |
| Episodic | 과거 실행 경험 | Task → Execution → Result → Outcome |
| Semantic | 재사용 가능한 사실·지식 | "Project DB = PostgreSQL", "API Auth = JWT" |
| Procedural | 작업 수행 절차 | "API 문서 분석 시: Endpoint 추출 → Parameter 분석 → Schema 분석" |

초기 구현에서는 각 타입을 별도 클래스로 분리하지 않는다. `MemoryItem`에
타입 필드를 두는 수준으로 시작하고, 필요해지면 분화한다.

## Context

현재 Agent 실행에 필요한 상태를 관리한다.

```python
class Context:

    messages        # 현재 대화/실행 메시지 (user/assistant/tool) — 순수 JSON 데이터 (ADR-0010)
    instructions    # system 지시 — messages와 분리 (Strategy가 덧붙이고 child가 상속)
    variables       # 실행 중 상태 변수 = RLM의 Environment (거대 입력은 variables['context'])
    metadata        # task, execution_id 등
```

Tool 결과와 child 결과는 별도 필드 없이 messages(관찰)와 Execution Tree에 남는다.
system 지시를 messages에 섞지 않는 이유는 [strategies.md](strategies.md#지시instructions와-context) 참조.

**Context는 현재 실행의 상태이며, 실행 종료 후 반드시 지속되어야 하는 것은 아니다.**
지속이 필요한 정보는 Memory에 Store한다.

### 멀티턴 — Conversation은 Context도 Memory도 아니다 (ADR-0010)

수명이 다른 셋을 섞지 않는다.

| | 무엇 | 수명 | 어디에 |
|---|---|---|---|
| **Context** | 한 `run` 안의 messages (tool 왕복 포함) | run 하나 | `Context.messages` |
| **Conversation** | run **사이**의 대화 연속 = 멀티턴 | 세션 | **앱의 저장소** |
| **Memory** | 실행 간 영속되는 *사실* | 영구 | `Memory` 구현체 |

`Agent.run(task, history=[...])`로 이전 턴들을 넣고, `result.metadata['messages']`로
이번 run의 전체 transcript를 돌려받는다. 코어는 대화를 저장하지 않는다.

```python
history = db.load(session_id)                      # 앱이 이미 갖고 있는 것
result = await agent.run(task, history=history)
db.save(session_id, result.metadata['messages'])   # 다음 턴에 그대로 다시 넘긴다
```

**대화를 Memory에 쌓지 말 것.** `retrieve`는 키워드 겹침 점수이고 순서 개념이 없다 —
"3번째 턴에서 뭐라고 했는지"를 복원할 수 없고, 매 턴이 쌓이면 진짜 기억이
"네 알겠습니다" 수백 개에 묻힌다. 둘은 층을 이룬다:

```
최근 N턴  →  history (원문 그대로, 순서 보존)
    ↓ 컨텍스트 창이 차면 오래된 턴을 잘라냄 (잘라내기 정책은 앱의 몫)
    ↓ 잘라내기 전에 모델이 remember 호출
남길 사실  →  Memory (요약된 사실, 순서 무관, 영구)
```

`messages`에는 파이썬 객체를 넣지 않는다 — `tool_calls`도 dict다. 앱이 DB·큐에 저장하는
대상이기 때문이다(`examples/worker.py`가 Redis 큐로 실어 나른다). 변환 책임은 Provider에 있다.

transcript는 `Agent.run`에서만 붙는다 — `spawn_agent`가 만드는 child의 `AgentResult`에는
실리지 않는다(재귀 context 폭발 방지). `Session` 객체를 코어에 두지 않는 이유는
`Agent.run`을 무상태로 남겨 멀티 워커에서 그대로 동작하게 하기 위해서다.

### 문맥의 객체화 — Environment(Context)

RLM의 핵심 관점(문맥을 "읽어야 할 텍스트"가 아닌 "프로그래밍 가능한 환경 변수"로
다룬다, [rlm-background.md](../overview/rlm-background.md))은 Strata에서
`Context.variables` + Tool의 조합으로 표현한다:

- 거대한 문서·데이터는 **메시지에 인라인하지 않고 `Context.variables`에 객체로 담는다**
  (RLM의 `ctx` 변수에 해당). 모델의 메시지 window에는 올라가지 않는다.
- 모델은 이 변수에 직접 접근할 수 없고, **Tool(예: `PythonTool` REPL)을 통해서만**
  조회·가공한다 — `len(ctx)`, `ctx[:100]`, 정규표현식 필터링 등.
- Recursive spawn 시 변수의 조각(sub-context)만 child의 Context에 넘겨
  window 한계를 우회한다.

즉 RLM의 `RLM(Prompt, Environment(Context))` 형태에서 Environment는 별도
abstraction이 아니라 **variables를 가진 Context + REPL Tool**이다.

Phase 3 판정: 이 매핑은 충분하되 두 가지 배선이 필요했다 — (1) Tool이 Context에 닿아야
한다(`ToolEnv`, ADR-0007), (2) `spawn_agent(context=...)`/`Agent.run(context=...)`가
variables에 조각/원본을 넣어야 한다. 둘 다 구현됐고 독립 Environment abstraction은 만들지 않는다.
구체적 흐름은 [strategies.md의 RLM](strategies.md#rlm-strategy--문맥을-환경으로-다루는-재귀) 참조.

## Agent

Provider, Strategy, Tools, Memory, Runtime을 조합하는 실행 단위.

```python
class Agent:

    def __init__(
        self,
        provider,
        strategy,
        tools=None,
        memory=None,
        instructions=None,   # root Context.instructions — child가 상속
        config=None,
    ):
        ...

    async def run(self, task, context=None) -> AgentResult: ...   # context → variables['context']
    runtime: Runtime | None                                        # 마지막 run의 Runtime (tree·usage 조회)
```

**Agent 자체에는 특정 Agent Pattern의 실행 로직을 넣지 않는다.**
`agent.run(task, context=None)`은 run당 하나의 Runtime을 만들고(ADR-0006), Context를 구성하고
(거대 입력은 variables로) `runtime.run_strategy`를 통해 Strategy에 실행을 위임할 뿐이다 — timeout 적용과
한도 초과의 계약 변환도 이 경로에서 일어난다.
동일한 Agent abstraction에서 Strategy만 교체하여 실행 패턴을 바꾼다
([ADR-0003](../adr/0003-strategy-as-first-class-abstraction.md)).
