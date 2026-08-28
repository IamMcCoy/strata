# 1. Agent

**English** | [한국어](../01-agent.md)

`Agent` is a **unit of composition**. How to execute (the pattern) is decided by the `Strategy`;
what to execute with (model, tools, memory) is decided by the objects you pass in. The Agent
itself has no execution logic.

```python
Agent(
    provider,                 # required — the model
    strategy,                 # required — the execution pattern
    tools=None,               # list[Tool]
    memory=None,              # a Memory implementation
    instructions=None,        # str — system instructions
    config=None,              # RuntimeConfig — execution limits
    on_delta=None,            # (text, execution_id) -> None. Providing it turns on streaming
)
```

Why `instructions` is separate from messages: the strategy needs to append its own pattern
instructions after it, and child agents need to inherit these instructions. Mixed into the
conversation, neither is possible.

## The entry point is `run`, and only `run`

```python
result = await agent.run(
    task,              # what to do this time
    context=None,      # huge input
    history=None,      # messages from previous turns
)
```

There is no second method like `stream()`. Streaming is the `on_delta` callback, and even with
the callback, `run` still returns a complete result. So you can turn streaming on and off and the
rest of your code stays the same.

`context` **does not go into messages.** Even if you pass a 100MB log, it is not inlined into the
conversation — it is kept as a variable, and the model handles it only through Python code
(→ RLM in [6. Strategy](06-strategies.md)).
`Agent.run(task, context=big)` is a declaration: "this input cannot be read in one pass."

## What comes back — `AgentResult`

```python
result.status      # 'completed' | 'failed' | 'budget_exceeded' | 'cancelled'
result.result      # the final text
result.evidence    # list of supporting evidence (Reflection puts per-round critiques and drafts here)
result.metadata    # additional information
```

Always present in `metadata`:

| key | |
|---|---|
| `messages` | The full transcript of this run. Pass it back as `history=` on the next turn |
| `run_id` | UUIDv7. The name that points to logs and the execution tree. Record it next to your app's task_id |
| `route` | If a router was used, which strategy was chosen |
| `reason` | The cause of a failure or limit overrun (`max_depth`, `timeout`, `provider_error`, etc.) |

## Failure is a result, not an exception

When a limit is exceeded or the model API is down, no exception is thrown. Doing so would
**throw away every token spent so far.** Instead it comes back as a status, and `result.result`
holds the answer so far.

```python
result = await agent.run(task)

if result.status != 'completed':
    logger.warning('run=%s %s (%s)', result.metadata['run_id'],
                   result.status, result.metadata.get('reason'))
# result.result is still usable — it contains a partial answer
```

| status | when |
|---|---|
| `completed` | Normal |
| `budget_exceeded` | `max_depth`, `max_iterations`, `max_children`, `token_budget`, or `timeout` exceeded |
| `failed` | Model API error (retries exhausted), or an exception thrown by a child agent |
| `cancelled` | Cooperative cancellation via `runtime.cancel()` |

**Bugs in your own code propagate as-is.** Swallowing typos and type errors into
`status='failed'` would make debugging impossible. Only "infrastructure errors" are swallowed.

## Execution records

```python
agent.runtime.usage                # total tokens for this run
agent.runtime.execution.root       # root of the execution tree
```

One `ExecutionNode` is one agent:

```python
node.task           # what it was asked to do
node.depth          # recursion depth
node.status         # outcome
node.iterations     # how many times the model was called
node.usage          # tokens this node spent directly
node.children       # child agents this node spawned
node.subtree_usage()  # itself + all descendants' tokens — the only answer to "which branch was expensive"
```

Code that prints the whole tree:

```python
def render(node, indent=0):
    print('  ' * indent + f'[{node.status}] {node.task[:40]} → {node.subtree_usage()["total_tokens"]} tokens')
    for child in node.children:
        render(child, indent + 1)

render(agent.runtime.execution.root)
```

`agent.runtime` belongs to the **last run**. A fresh Runtime is created per run, and the child
agents that run spawned share the same Runtime. So an `Agent` instance is stateless and can be
reused as-is across multiple workers.

## Logging

The library does not configure logging. Turning it on is the app's job:

```python
import logging
logging.basicConfig(level=logging.INFO)      # agent.started / agent.finished
logging.getLogger('strata').setLevel(logging.DEBUG)   # + provider.request / agent.spawned / tool execution
```

Every line carries `run=` and `exec=`, so you can pick out a single execution.
