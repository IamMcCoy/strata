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

### API Key와 의존성

- 키 우선순위: **명시적 인자 > Provider별 관례 환경변수**
  (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).
- 프레임워크는 키를 저장·로깅하지 않고 SDK에 전달만 한다.
  `.env` 로딩도 프레임워크가 하지 않는다 — 앱의 몫이며 `.env`는 gitignore된다.
- Provider SDK는 **optional extras**로 설치한다 (`uv add 'strata[openai]'`) —
  코어는 의존성 0을 유지하고, SDK import는 Provider 생성 시점에 일어나므로
  extras 없이도 `import strata`는 동작한다.

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

구현체: `InMemory`(Phase 4 최초 구현), `RedisMemory`, `VectorMemory`,
`SQLMemory`, `FileMemory`, `CustomMemory`.

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

    messages        # 현재 대화/실행 메시지 (user/assistant/tool)
    instructions    # system 지시 — messages와 분리 (Strategy가 덧붙이고 child가 상속)
    variables       # 실행 중 상태 변수 = RLM의 Environment (거대 입력은 variables['context'])
    metadata        # task, execution_id 등
```

Tool 결과와 child 결과는 별도 필드 없이 messages(관찰)와 Execution Tree에 남는다.
system 지시를 messages에 섞지 않는 이유는 [strategies.md](strategies.md#지시instructions와-context) 참조.

**Context는 현재 실행의 상태이며, 실행 종료 후 반드시 지속되어야 하는 것은 아니다.**
지속이 필요한 정보는 Memory에 Store한다.

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
