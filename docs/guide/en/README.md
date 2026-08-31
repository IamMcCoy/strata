# Strata User Guide

**English** | [한국어](../README.md)

Each document is **self-contained.** None of them requires reading another document first.

| | |
|---|---|
| [1. Agent](01-agent.md) | Assembly and execution. `Agent.run` is the single entry point |
| [2. Provider](02-providers.md) | Attaching models — OpenAI, Claude, Gemini, vLLM, Ollama, streaming, errors, fallback |
| [3. Tool](03-tools.md) | Building tools. Implement just one method: `execute(self, env, **kwargs)` |
| [4. Memory](04-memory.md) | Facts that persist across runs. Storing is explicit, retrieval is automatic |
| [5. Multi-turn](05-conversation.md) | The app owns the conversation history. Trim it when it gets long |
| [6. Strategy](06-strategies.md) | The five execution patterns and custom strategies |
| [7. Limits, Cancellation, Observability](07-limits.md) | The plumbing that prevents runaway execution |

Mechanical listings of classes, functions, and parameters are not written by hand — when a
parameter changes, the document becomes a lie and nobody fixes it. They are generated from
the docstrings in the code:

```bash
make docs      # → docs/api/index.html (generated artifact, not committed to git)
```

| | This guide | `docs/api/` |
|---|---|---|
| Answers | "How do I do multi-turn?" | "What are `RouterStrategy`'s arguments?" |
| How it's made | By hand | `make docs` |

## Installation

```bash
uv add strata               # the core has zero runtime dependencies
uv add 'strata[openai]'     # providers are extras: openai / anthropic / gemini / redis / all
```

Python 3.12 or later.

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

## Five Minutes

```python
import asyncio
from strata.agent import Agent
from strata.providers import OpenAIProvider
from strata.strategies import ReActStrategy
from strata.tools import Tool


class Add(Tool):
    name = 'add'
    description = 'Add two integers'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
        'required': ['a', 'b'],
    }

    async def execute(self, env, **kwargs):
        return kwargs['a'] + kwargs['b']


async def main():
    agent = Agent(
        provider=OpenAIProvider(model='gpt-4o-mini'),
        strategy=ReActStrategy(),
        tools=[Add()],
    )
    result = await agent.run('Compute 123456 + 654321 using the add tool')
    print(result.status, result.result)


asyncio.run(main())
```

Only three things to remember:

- **You only register** — pass Provider, Tool, and Memory as arguments and you're done. There is no wiring.
- **The entry point is `run`, and only `run`** — streaming, multi-turn, huge inputs: they are all arguments to `run`.
- **Failure is a result, not an exception** — limit overruns and model errors come back via `result.status`.

Working examples live in [`examples/`](../../../examples) and all of them run **without API keys**.
