# 7. Limits, Cancellation, Observability

**English** | [한국어](../07-limits.md)

Agents recurse and iterate. Left unchecked, **cost explodes exponentially.** The plumbing that stops
that lives here.

## The Runtime enforces limits

```python
from strata import Agent, RuntimeConfig

agent = Agent(provider=..., strategy=..., config=RuntimeConfig(
    max_depth=5,          # recursion depth
    max_iterations=30,    # how many times one agent may call the model
    max_children=8,       # how many children one agent may spawn
    token_budget=None,    # token cap for the whole run
    timeout=None,         # seconds, for the whole run
))
```

**A strategy gets caught even if it knows nothing about limits.** The checks live inside
`runtime.generate` and `runtime.spawn_agent`, not in the strategy. Even a custom strategy written by
someone else is safe to use.

Exceeding a limit comes back as a **result, not an exception**:

```python
result = await agent.run(task)
if result.status == 'budget_exceeded':
    print(result.metadata['reason'])   # 'max_depth' | 'max_iterations' | 'max_children'
                                       # | 'token_budget' | 'timeout'
    print(result.metadata['limit'])    # the value that was hit
    print(result.result)               # the answer so far — not thrown away
```

Making it an exception would throw away every token spent up to that point. A partial answer beats
nothing.

If `max_depth` or `max_children` is hit mid-recursion, the parent model receives that fact as an
observation:

```
{'status': 'budget_exceeded', 'metadata': {'reason': 'max_children', 'limit': 8}}
```

The model reads it as a signal: "stop delegating and answer with what you have." The execution
doesn't die.

## Strategies can suggest limits

Some limits' right values are known only to the strategy. `ReflectionStrategy(rounds=4)` structurally
needs `1 + 4*2 = 9` children, but with the default `max_children=8` it gets silently cut short. So
the strategy makes a suggestion:

```python
ReflectionStrategy(rounds=4)              # suggests raising max_children to 9
ReActStrategy(max_iterations=10)          # gives the loop cap next to the strategy
RecursiveStrategy(max_depth=2, max_children=3)
```

There is only one precedence order:

```
values you set explicitly in RuntimeConfig  >  the strategy's suggestion  >  defaults
```

```python
Agent(strategy=ReflectionStrategy(rounds=4))                         # max_children 8 → 9
Agent(strategy=ReflectionStrategy(rounds=4),
      config=RuntimeConfig(max_children=3))                          # 3. You win
```

**Enforcement still belongs to the Runtime.** A suggestion only changes where the value comes from.
And limits derived from a strategy act **only as a floor** — they raise, never lower. Limits are
shared by the whole run, so lowering to the 5 that `rounds=2` needs would also shave the headroom of
other strategies running inside.

Get a name wrong and it's caught **at construction time**:

```python
ReActStrategy(max_iteration=10)
# TypeError: unknown limit(s) ['max_iteration']; known: ['max_children', 'max_depth', ...]
```

## Cancellation

Two kinds, with different endings.

**Cooperative cancellation** — keeps the answer so far:

```python
task = asyncio.create_task(agent.run(long_job))
...
agent.runtime.cancel('user aborted')       # blocks new model calls and child spawns
result = await task
result.status                              # 'cancelled'
result.result                              # the answer so far
result.metadata['reason']                  # 'user aborted'
```

Tokens already spent are not thrown away, so **the stop button a user presses is this one**.

**Hard cancellation** — `asyncio.CancelledError`. It propagates as usual, but the execution tree
records it as `cancelled`. A tool already in flight runs to completion (cancellation lags by at most
one tool).

## Observability

### Tokens — two layers

```python
agent.runtime.usage                        # total for the whole run
agent.runtime.execution.root.usage         # what the root node spent directly
node.subtree_usage()                       # the whole branch — the only meaningful value in recursion
```

In recursion, "which branch was expensive" is answerable only per node. Looking at the total alone,
you can't find the cause.

### Execution tree

```python
def render(node, indent=0):
    cost = node.subtree_usage()['total_tokens']
    print('  ' * indent + f'[{node.status}] d{node.depth} {node.task[:40]!r} · {cost} tokens')
    for child in node.children:
        render(child, indent + 1)

render(agent.runtime.execution.root)
```

```
[completed] d0 'Write report' · 12,430 tokens
  [completed] d1 'Survey open source' · 5,120 tokens
    [completed] d2 'Deep dive: RLM family' · 2,050 tokens
  [budget_exceeded] d1 'Survey commercial' · 1,900 tokens
```

### Logs

The library configures no logging — turning it on is the app's job:

```python
import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('strata').setLevel(logging.DEBUG)
```

| Level | What appears |
|---|---|
| INFO | `agent.started` / `agent.finished` / `router.selected` |
| DEBUG | `provider.request` / `provider.response` / `agent.spawned` / `agent.completed` / `memory.retrieve` |
| WARNING | `provider.error` / `model.tool_call_may_have_leaked_as_text` |

Every line carries `run=` and `exec=`, so one execution can be picked out:

```
run=01a041a3-1e5e-7a58-… exec=exec_0 agent.started task=Write report
run=01a041a3-1e5e-7a58-… exec=exec_1 agent.spawned parent=exec_0 depth=1 task=Survey open source
```

The `run_id` is issued by the core (UUIDv7 — it sorts chronologically). `exec_0` is reused per run,
so on its own it mixes up records across processes and runs. The app writes the `run_id` next to its
own task_id:

```python
db.save(task_id, run_id=result.metadata['run_id'])
```

### One warning worth knowing

```
WARNING model.tool_call_may_have_leaked_as_text names=['add'] text=<|tool_call>call:add{...}
```

It means the model failed to follow the tool call format and vendor-specific syntax **leaked into
the body text**. Since the tool calls are empty, the framework treats it as the "final answer" and
ends the loop — garbage becomes the answer.

It happens with small models or servers without a tool parser configured. When you see this warning,
use a bigger model or check the server's tool parser configuration. The behavior is not changed
(false positives are possible).

## The order for cutting cost

1. **Set limits first.** `token_budget` and `timeout` are the last line of defense against
   accidents.
2. **Route chores like classification and summarization to a cheap model.** Override the router's
   `classify()` to run just the classification on a different provider.
3. **Find the expensive branch with `subtree_usage()`.** Usually one recursion accounts for most of
   the total cost.
4. **Don't put huge input in messages.** Pass it via `context=` and it doesn't burn the
   conversation window.
