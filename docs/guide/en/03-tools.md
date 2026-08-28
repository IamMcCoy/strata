# 3. Tool

**English** | [한국어](../03-tools.md)

The model's only channel to the outside world. **You implement exactly one thing: `execute`.**

```python
from strata import Tool


class SearchTool(Tool):
    name = 'search'                                   # the name the model calls
    description = 'Search the internal wiki'          # one line on when to use it — the model reads this
    input_schema = {                                  # JSON Schema
        'type': 'object',
        'properties': {
            'query': {'type': 'string', 'description': 'What to search for'},
            'limit': {'type': 'integer', 'description': 'Max results'},
        },
        'required': ['query'],
    }

    async def execute(self, env, query='', limit=5, **kwargs):
        rows = await db.search(query, limit)
        return [{'title': r.title, 'url': r.url} for r in rows]
```

```python
agent = Agent(provider=..., strategy=ReActStrategy(), tools=[SearchTool()])
```

## Return values

Strings go through as-is; everything else is serialized to JSON and handed to the model
as an observation. **Remember the model will read it** — returning a giant dump just
burns context.

```python
return f'{len(rows)} results. Top 3: ...'  # good
return rows                                # bad if it's 10,000 rows
```

## `env` — the only way to reach the Runtime

Most Tools ignore it. Use it only when you need it.

```python
async def execute(self, env, **kwargs):
    env.context.variables['count'] = 1      # state for this run
    env.context.metadata['task']            # the original task
    env.runtime.memory                      # the Memory implementation
    result = await env.runtime.spawn_agent(  # spawn a child agent
        'Summarize just this fragment', env.context, context=chunk,
    )
```

**Creating a child agent must go through `env.runtime.spawn_agent()`.** Depth and
child-count limit checks, execution-tree registration, and token accounting all hang off
this point. If you construct and run an `Agent()` directly, that run happens outside the
limits and never shows up in the tree.

## Exceptions become observations

An exception thrown by a Tool doesn't kill the run — it's passed to the model as a string:

```
Tool 'search' failed: ConnectionError('timed out')
```

The model reads it and fixes its arguments or tries another approach. **A run doesn't die
from the model's mistakes.** Calling a nonexistent tool returns the list of available ones.

So there's no need to wrap defensive `try/except` inside your Tool. What matters is that
**the exception messages you throw are useful to the model**:

```python
raise ValueError('query must not be empty')          # good — the model can fix this
raise ValueError('e')                                 # bad
```

## The three built-in tools

```python
from strata import MemoryTool, SpawnAgentTool, PythonTool
```

| | Name | What it does |
|---|---|---|
| `MemoryTool` | `remember` | The model explicitly stores facts to keep for future runs |
| `SpawnAgentTool` | `spawn_agent` | Delegates a subtask to a child agent with a fresh context |
| `PythonTool` | `python` | A stateful Python REPL. `llm_query` is injected |

`SpawnAgentTool` and `PythonTool` are attached **automatically** by `RecursiveStrategy`
and `RLMStrategy` respectively. You don't need to put them in `tools=` yourself.

> ⚠️ **`PythonTool` is not a sandbox.** Code the model writes runs with this process's
> privileges — files, network, environment variables, all of it. **Trusted environments
> only.** If end-user input ever reaches the prompt, read "Replacing tools" below.

## Replacing tools — same name wins

Put a tool with the **same `name`** as a strategy's default tool into `tools=` and yours
is used. That's the path to a sandbox:

```python
class SandboxedPython(Tool):
    name = 'python'                      # same name as PythonTool → this one wins
    description = 'Execute Python code in an isolated container'
    input_schema = {'type': 'object', 'properties': {'code': {'type': 'string'}},
                    'required': ['code']}

    async def execute(self, env, code='', **kwargs):
        return await my_container.run(code)


agent = Agent(provider=..., strategy=RLMStrategy(), tools=[SandboxedPython()])
```

Why the core doesn't ship an in-process sandbox: it's well established that in-process
isolation in CPython can be bypassed (escape routes keep being found through the object
graph, exception objects, frames, and so on), and **a partial defense creates the illusion
of safety, making it more dangerous than nothing at all.** With nothing, you only feed it
trusted input; with something, you feed it untrusted input.

An isolation implementation has one problem to solve: `llm_query` has to call back to the
host across the process/container boundary. The core gives you `env.runtime.spawn_agent()`;
the RPC on top of it is the implementation's job.
