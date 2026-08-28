# 6. Strategy

**English** | [한국어](../06-strategies.md)

**The execution pattern.** It decides how many times and in what order the model is called, and how
tools and child agents are woven together. Swap only the strategy — not the `Agent` — and the entire
execution style changes.

```python
Agent(provider=..., strategy=ReActStrategy(), tools=[...])
Agent(provider=..., strategy=RLMStrategy())         # everything else stays the same
```

## The five

| | When | How |
|---|---|---|
| **ReAct** | The default. Tasks a few tool calls can answer | think → tool call → observe → repeat → answer |
| **Recursive** | Tasks that split into a few independent subtasks | ReAct + `spawn_agent` tool |
| **RLM** | Input that doesn't fit in one window | ReAct + Python REPL + `llm_query` recursion |
| **Reflection** | Quality matters more than speed | draft → critique → revise (fixed rounds) |
| **Router** | When you don't know which pattern fits | picks one and that one solves it to the end |

### ReAct

```python
ReActStrategy(prompt=None, model_params=None, description=None, **limits)
```

The loop ends when the model answers in text without calling a tool. That's why "when you're done,
answer without tools" is part of the pattern instructions.

### Recursive

```python
RecursiveStrategy()
```

The `spawn_agent` tool is attached automatically. When the model writes a subtask as a self-contained
brief and hands it over, a child solves it in a **clean context** and returns only the result. The
child cannot see the parent's conversation, so writing "as mentioned above" won't work.

By default the child inherits the same strategy and can recurse again. Depth and child count are
capped by the limits.

### RLM

```python
RLMStrategy()
```

Pass huge input via `Agent.run(task, context=big)` and it goes into a **variable**, not the
conversation window; the model reaches it only through the `python` tool. It slices the input into
chunks, hands them to multiple children via `llm_query(prompt, context=chunk)`, and collects the
results in variables.

```python
agent = Agent(provider=..., strategy=RLMStrategy())
result = await agent.run('Find the error patterns in this log', context=huge_log)
```

Variables the model creates in the REPL appear as a list in the next turn's instructions. `llm_query`
is injected into that REPL as well.

> ⚠️ The `python` tool is not a sandbox. It is for trusted environments only; if you need isolation,
> build a container implementation with the same `name='python'` and register it in `tools=` —
> yours will be used instead.

### Reflection

```python
ReflectionStrategy(rounds=2, worker=None, critic_prompt=..., description=None)
```

Draft, critique, and revision are **all spawned as child agents**. The key is that the critic cannot
see the conversation that produced the draft — a critique made inside a context steeped in its own
draft is no critique at all.

Rounds are fixed and there is no early exit. The moment you ask the critic "is this enough now," the
model gets to judge whether it has satisfied itself — and preventing exactly that is this pattern's
reason to exist. To turn it off, use `rounds=0`.

```python
result = await agent.run('Write a company introduction paragraph')
result.result                    # final version
result.evidence                  # [{'critique': ..., 'draft': ...}, ...] per-round records
result.metadata['rounds_completed']
```

Use `worker=` to swap the strategy in charge of drafting and revising — with
`worker=RecursiveStrategy()` the draft itself is produced recursively.

### Router

```python
RouterStrategy(routes, *, default, context_route='rlm', prompt=None, description=None)
```

```python
agent = Agent(provider=..., strategy=RouterStrategy({
    'react':      ReActStrategy(),
    'recursive':  RecursiveStrategy(),
    'rlm':        RLMStrategy(),
    'reflection': ReflectionStrategy(),
}, default='react'))
```

It chooses in two steps:

1. **Deterministic rule first** — if huge input arrived via `run(task, context=...)`, it goes to
   `context_route` (default `'rlm'`) without asking. "It doesn't fit in one window" is a fact, not a
   judgment call; asking the model only spends tokens and gives it a chance to be wrong. In this case
   there are **zero** model calls.
2. **Otherwise, one tool call** — it advertises `route(strategy: enum[...])`, calls once, and reads
   the chosen name. Because it's an enum, the choosable values are fixed by the schema, and if the
   model can't follow the format, it falls back to `default`.

**The chosen strategy runs in the same Context, as is.** Spawning it as a child would hide the
conversation history from the child, so wrapping a router would break multi-turn. Which strategy was
chosen is recorded in the result:

```python
result.metadata['route']      # 'reflection'
```

`default` is a required argument. A routing failure is a total failure (no strategy gets chosen), so
we made it impossible to leave the default out.

## Tuning the decision criteria — the cheapest tuning there is

The router assembles a classification prompt from each strategy's `description`. The defaults are
generic English and won't match your domain. **Rewrite them in your domain's terms and accuracy goes
up without touching the model or the prompt:**

```python
RouterStrategy({
    'lookup': ReActStrategy(description='Simple lookups and calculations. Questions answerable directly via internal APIs.'),
    'bulk':   RLMStrategy(description='Bulk processing of large logs and documents.'),
    'report': ReflectionStrategy(description='Documents that go out to customers. Work where a draft needs polishing.'),
}, default='lookup')
```

If `description` is empty, the class name stands in for it, so custom strategies join the routing
without doing anything.

## Changing the pattern instructions

Each strategy carries fixed instructions sent to the model (the harness prompt). The system message
is assembled like this:

```
your instructions  +  the strategy's prompt  +  the strategy's current state (environment)
```

```python
ReActStrategy(prompt='...my own rules...')    # replace wholesale
ReActStrategy(prompt='')                      # turn off
```

You can also append to the exported constants — `REACT_PROMPT`, `RECURSIVE_PROMPT`, `RLM_PROMPT`,
`ROUTER_PROMPT`, `REFLECTION_CRITIC_PROMPT`. **The exported constant is exactly the text the model
sees.**

```python
from strata import REACT_PROMPT
ReActStrategy(prompt=REACT_PROMPT + '\n\nAlways answer in Korean.')
```

## Custom strategies

```python
from strata import Strategy, AgentResult


class TwoPass(Strategy):
    description = 'First make a plan, then execute according to that plan.'

    async def execute(self, context, runtime) -> AgentResult:
        plan = await runtime.generate(context, instructions='First, only make a plan.')
        context.messages.append({'role': 'assistant', 'content': plan.text})
        final = await runtime.generate(context, instructions='Now execute according to the plan.')
        return AgentResult(result=final.text)
```

There is only one rule to keep: **reach resources only through `runtime`.**

```python
await runtime.generate(context, tools=..., instructions=...)     # model
await runtime.execute_tool(name, arguments, context)             # tool
await runtime.spawn_agent(task, context, strategy=..., context=...)  # child agent
runtime.memory                                                    # Memory
runtime.execution                                                 # execution tree
```

Calling `runtime.provider.generate()` directly skips all limit checks, token accounting, and
warnings. Constructing an `Agent()` yourself and using it as a child means that execution runs
outside the limits and never appears in the tree.

**You get stopped even without knowing the limits.** Call `runtime.generate` endlessly and you hit
`max_iterations` and end with `budget_exceeded`. A custom strategy needs no defense of its own.
