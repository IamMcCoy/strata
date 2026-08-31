# Strata

**English** | [한국어](README.md)

> A composable runtime for agentic systems.

**Strata** is an extensible Agent Execution Framework that lets you implement and compose
various Agentic Patterns (ReAct, Recursive/RLM, Reflection, …) on top of a single Runtime.
It abstracts Provider, Tool, Memory, Context, Strategy, and Execution as independent primitives,
and the Runtime wires them together, executes them, and observes them.

**Zero runtime dependencies.** Provider SDKs are installed optionally — so it never conflicts
with the `openai`/`anthropic` versions your app has pinned.

```python
from strata.agent import Agent
from strata.providers import OpenAIProvider
from strata.runtime import RuntimeConfig
from strata.strategies import RLMStrategy

agent = Agent(
    provider=OpenAIProvider(model='gpt-4o-mini', model_params={'temperature': 0.3}),
    strategy=RLMStrategy(),             # swappable with ReActStrategy / RecursiveStrategy
    instructions='Answer concisely.',   # system instructions — inherited by children
    config=RuntimeConfig(max_depth=3, token_budget=200_000),
)

# Huge inputs go in as the variable `context`, not as messages — the model slices them
# with the python tool and passes only slices to child agents via llm_query,
# collecting the results (RLM).
result = await agent.run('Sum up the key figures from every chapter of this document.', context=huge_document)
print(result.status, result.result)   # completed | failed | budget_exceeded | cancelled
```

Swap only `strategy=` on the same Agent and the execution pattern changes. Limits
(depth/children/iterations/token/timeout) are enforced by the **Runtime**, not the Strategy,
so they hold even when a Custom Strategy knows nothing about them — and on excess you get a
`budget_exceeded` result (including the answer so far) instead of an exception.

## Components

### Provider

| | Usage | Verified against real API |
|---|---|---|
| OpenAI | `OpenAIProvider(model='gpt-4o-mini')` | ✅ streaming·tool·usage |
| Gemini | `GeminiProvider(model='gemini-3.5-flash-lite')` | ✅ streaming·tool·usage |
| vLLM | `OpenAIProvider(base_url='http://host:port/v1')` | ✅ streaming·usage <sup>1</sup> |
| Claude | `AnthropicProvider(model='claude-sonnet-5')` | ❌ unverified |
| OpenRouter | `OpenAIProvider(base_url='https://openrouter.ai/api/v1')` | ❌ unverified |
| Ollama | `OpenAIProvider(base_url='http://localhost:11434/v1')` | ❌ unverified |

<sup>1</sup> To use tools with vLLM, the server must be started with `--enable-auto-tool-choice`.

OpenAI-compatible endpoints are the **same code** with only `base_url` changed. Only
Claude and Gemini need separate implementations — both have fundamentally different message formats.
Retries are left to the SDK: `Provider(..., max_retries=2, timeout=30)`.

### Memory — persistence across runs (separate from Context, [ADR-0002](docs/adr/0002-context-memory-separation.md))

| | When | Cost |
|---|---|---|
| `InMemory()` | development·testing·single process | none |
| `SQLiteMemory('mem.db')` | persistence + multiple workers (same host) | stdlib `sqlite3` |
| `RedisMemory(client)` | workers spread across hosts | the client is **injected** |

`retrieve` happens automatically in `Agent.run` (→ system instructions); `store` is explicit,
by the model via `MemoryTool`. Scope is separated per instance: `SQLiteMemory(path, namespace=f'user:{uid}')`.

### Strategy

`ReActStrategy` / `RecursiveStrategy` / `RLMStrategy` / `ReflectionStrategy` / `RouterStrategy`.
Each Strategy carries its own pattern's harness prompt (tool discipline·termination protocol·delegation
rules) and assembles system = `instructions` + `prompt` + current state. A Tool implements only one
method: `execute(self, env, **kwargs)`.

`RouterStrategy` picks the strategy that fits the task and lets it solve the task to completion —
when a huge input arrives it goes to RLM without asking (that's a fact, not a judgment), otherwise it
decides with a single `route(strategy: enum)` tool call. The chosen strategy runs **in the same
Context**, so wrapping a router does not break multi-turn. The decision basis is each strategy's
`description`, and overriding it with domain terms is the cheapest tuning:

```python
RouterStrategy({
    'lookup': ReActStrategy(description='Simple lookups and calculations. Questions answerable directly via internal APIs.'),
    'bulk':   RLMStrategy(description='Bulk processing of large logs and documents.'),
}, default='lookup')
```

`ReflectionStrategy` is an orchestrator that spawns draft·critique·revision all as children,
so it never calls `generate` itself — the invariant that a child cannot see the parent's conversation
directly becomes "a critic untainted by its own draft". Strategies compose via `worker=`:
`ReflectionStrategy(rounds=2, worker=RecursiveStrategy())`.

> ⚠️ **`RLMStrategy`'s `PythonTool` is not a sandbox.** Model-generated code runs with this
> process's privileges — files, network, environment variables, all of it. **Trusted environments
> only.** If end-user input reaches the prompt, build an isolated implementation (container·remote
> kernel) under the same `name='python'` and register it in `tools=[...]` — the registry beats the
> strategy's default tool.
> Why the core does not provide an in-process sandbox:
> [ADR-0015](docs/adr/0015-no-in-process-sandbox.md).

## Key features

### Streaming — a callback, not a second entry point ([ADR-0012](docs/adr/0012-streaming-as-a-side-channel.md))

```python
agent = Agent(..., on_delta=lambda text, execution_id: queue.put_nowait(text))
```
`generate` returns a **complete `ModelResponse`** regardless of streaming. So the Strategy knows
nothing about streaming, and limit·usage accounting stays on a single path. In recursion,
`execution_id` tells you which child is speaking.

### Multi-turn — the core does not own conversation history ([ADR-0010](docs/adr/0010-conversation-history-is-not-core-state.md))

```python
history = db.load(session_id)
result = await agent.run(task, history=history)
db.save(session_id, result.metadata['messages'])
```
`Agent.run` stays stateless, so it works as-is with multiple workers.
`Context` (one run) ≠ `Conversation` (between runs) ≠ `Memory` (persisted facts) — three different things.

### Cancellation — two kinds ([ADR-0011](docs/adr/0011-run-id-and-two-kinds-of-cancellation.md))

| | How | Partial result |
|---|---|---|
| Hard | `asyncio.Task.cancel()` | none |
| Cooperative | `runtime.cancel(reason)` | **keeps the answer so far** |

Cooperative cancellation stops **before** the Provider call, so LLM cost after cancellation is zero.

### Errors — infrastructure vs. programming ([ADR-0013](docs/adr/0013-provider-errors-become-a-result-contract.md))

| | Outcome |
|---|---|
| 429·5xx·timeout (after retries are exhausted) | `status='failed'` + **keeps the answer so far** |
| `TypeError` and other bugs in my code | raises as-is — never swallowed |

A 30-minute recursion is not wiped out wholesale by a rate limit on the last call.
If you need a fallback: `Agent(provider=FallbackProvider([openai, claude]), ...)`.

### Observability — stdlib `logging`

```python
logging.basicConfig(level=logging.DEBUG)      # the library only attaches a NullHandler
```
```text
run=01a03c7b-… exec=exec_0 agent.started task=root task
run=01a03c7b-… exec=exec_2 agent.spawned parent=exec_0 depth=1 task=expensive slice
run=01a03c7b-… exec=exec_0 agent.finished status=completed tokens=115
```
`run_id` (UUIDv7, issued by the core) ties lines together across processes. Tokens come in two
layers — `Runtime.usage` (run total) and `ExecutionNode.usage`/`subtree_usage()` (per node; in
recursion, which branch was expensive).

## Installation

Not yet published to PyPI (distribution name·license undecided). Install directly from git:

```bash
uv add git+https://github.com/IamMcCoy/strata.git
```

The core has zero dependencies. Pick only the SDKs you use as extras:

```bash
uv add 'strata[openai] @ git+https://github.com/IamMcCoy/strata.git'
# anthropic / gemini / redis / all
```

Type hints included (PEP 561, `py.typed`).

## Import Paths

Names are grouped by role — `strata.agent` / `strata.providers` / `strata.strategies` /
`strata.tools` / `strata.memory` / `strata.runtime`.

```python
from strata.agent import Agent
from strata.providers import OpenAIProvider
from strata.strategies import ReActStrategy
```

Everything is importable from the top level too (`from strata import Agent`). Same objects —
`tests/test_packaging.py` enforces that the two paths never drift apart.

## Examples

```bash
uv run python examples/react.py           # fake provider — works without keys
uv run python examples/recursive.py       # recursion + Execution Tree
uv run python examples/rlm.py             # handling huge inputs as variables
uv run python examples/memory.py          # memory across runs
uv run python examples/conversation.py    # multi-turn + Memory layer
uv run python examples/observability.py   # logs + per-node tokens

uv run python examples/providers.py       # real APIs — calls only Providers with keys
make redis-up && uv run python examples/worker.py   # Redis queue + 2 worker processes
```

## Documentation

- [Documentation index](docs/README.md) — recommended reading order
- [Architecture](docs/architecture/architecture.md) · [Design](docs/design/abstractions.md)
- [ADR](docs/adr/README.md) — 12 expensive-to-reverse decisions and their rationale
- **[User guide](docs/guide/en/)** — assembly·providers·tools·memory·multi-turn·strategies·limits
- [Changelog](CHANGELOG.md)
- [Roadmap](docs/roadmap.md) · [Contributing guide](docs/CONTRIBUTING.md)

## Status

Phases 1–8 complete (except 6) — ReAct/Recursive/RLM/Reflection/Router Strategy, strategy
composition, full Runtime limits, 3 Memory backends, multi-turn, cancellation, streaming,
4 Providers, logging·per-node tokens.
What remains is Phase 6 (Events)·Phase 9 (Plugin) — both deferred until they have a consumer.
Details in the [roadmap](docs/roadmap.md).

## Development environment

Python 3.12 + [uv](https://docs.astral.sh/uv/).

```bash
make install            # uv sync
make test               # unit tests — zero external deps, never goes out to the network
make lint               # full pre-commit
make check              # lint + test (before committing)
make test-integration   # real Redis + multiprocess (requires docker)
make test-providers     # real endpoints — without a base_url this goes out to paid APIs
make help               # all commands
```

Integration tests are excluded from the default run via the `integration` marker. `make test`
never goes out to the network even when API keys are in the environment — to run everything,
`uv run pytest -m integration`.

For branching strategy and code style, see the [contributing guide](docs/CONTRIBUTING.md).
Contribution commits require a [DCO](docs/CONTRIBUTING.md#dco-developer-certificate-of-origin) sign-off (`git commit -s`).

## License

[Apache License 2.0](LICENSE)
