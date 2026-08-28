# 5. Multi-turn

**English** | [한국어](../05-conversation.md)

**The core does not own conversation history.** The app stores it, passes it in every
turn, and gets it back.

```python
history = db.load(session_id)                        # what the app already has
result = await agent.run(task, history=history)
db.save(session_id, result.metadata['messages'])     # pass it back in unchanged next turn
```

That's all of it. No `Session` object, no `agent.chat()`.

## Why the core doesn't own it

To keep `Agent` stateless. If the core held state, **you couldn't spread across multiple
workers** — an Agent instance can't be serialized and sent through a queue. With the
current structure, each worker builds its own `Agent` and only receives `history` from
the queue.

And the app already has the conversation in its DB. Having the core hold it too is
double bookkeeping.

## `messages` is pure JSON

It's what the app puts into DBs and queues, so no Python objects are mixed in. Tool calls
are dicts too:

```python
[
  {'role': 'user', 'content': 'What is 1 plus 2?'},
  {'role': 'assistant', 'content': None,
   'tool_calls': [{'name': 'add', 'arguments': {'a': 1, 'b': 2}, 'id': 'call_1',
                   'provider_state': {}}]},
  {'role': 'tool', 'name': 'add', 'tool_call_id': 'call_1', 'content': '3'},
  {'role': 'assistant', 'content': 'It is 3', 'tool_calls': []},
]
```

`json.dumps(result.metadata['messages'])` just works. Ship it to Redis, Postgres, SQS,
anywhere.

`provider_state` is a pouch the core round-trips without interpreting. For example,
Gemini 3.x tools don't work at all unless `thought_signature` is echoed back — vendor-
specific values like that live here. **Don't drop it; store it as-is and return it as-is.**

## Don't confuse it with Memory

| | `history` | `Memory` |
|---|---|---|
| Question | "What did I say earlier?" | "Which editor did I say I use?" |
| Content | Verbatim | Distilled facts |
| Order | Yes | No |
| Stored | Accumulates automatically | Explicitly, by the model |

**Don't pile the conversation into Memory.** Memory retrieval is score-based and has no
concept of order at all, so "what was said on the 3rd turn" cannot be reconstructed. No
scoring function fixes that — order is a problem that needs a different data structure.
On top of that, if every turn accumulates, boilerplate like "sure, got it" spreads across
all items, wrecks retrieval scores, and the real memories get buried in between.

The two form layers:

```
Recent N turns  →  history (verbatim, order preserved)
    ↓ when the context fills up, trim old turns
    ↓ before trimming, the model keeps just the facts via remember
Facts to keep   →  Memory (order-free, permanent)
```

## When conversations get long

**The core does not trim.** It concatenates what it's given, as-is. Trimming policy
differs per app; counting tokens needs a per-model tokenizer, which breaks the zero-
dependency rule; and the app that owns the conversation knows best which turns matter.

On overflow the provider returns `400 context_length_exceeded`, and you get back
`status='failed'` **along with the answer so far**. No crash, but this is an error retry
can never fix — if you've attached a fallback, the next provider fails identically and
you just spend money.

### Naive trimming breaks

```python
history[-20:]      # ← don't do this
```

Because tool round-trips come in **pairs**:

```python
{'role': 'assistant', 'tool_calls': [{'id': 'call_1', ...}]}   # ← trim this away
{'role': 'tool', 'tool_call_id': 'call_1', ...}                # ← keep only this and you get a 400
```

The provider rejects the request if the assistant message that `tool_call_id` points to
is missing. The reverse (call kept, result missing) is rejected too.

### `trim_history`

```python
from strata import trim_history

history = trim_history(db.load(session_id), keep_turns=10)
result = await agent.run(task, history=history)
```

A turn starts at a `role='user'` message, and all of that turn's tool round-trips follow
along until the next user message. So **turn boundaries are exactly the safe cut points**.

Why `keep_turns` counts turns, not messages: with tools, one turn can become ten
messages, so message count is unpredictable. "The last 10 turns" is predictable.

**It does not count tokens.** If a single turn is big enough to blow the context, this
can't stop it. At that point, replace old turns with a summary, or move just the facts
into Memory and drop the verbatim text.

## Riding a queue to multiple workers

`messages` is pure JSON, so just ship it as-is:

```python
# producer
queue.push({'task_id': tid, 'task': task, 'history': db.load(session_id)})

# worker (different process, different host)
job = queue.pop()
agent = Agent(provider=..., strategy=..., memory=SQLiteMemory('m.db', namespace=job['user']))
result = await agent.run(job['task'], history=job['history'])
db.save(job['task_id'], result.metadata['messages'], run_id=result.metadata['run_id'])
```

The queue itself stays out of the core — `Agent` can't be serialized, so the worker must
own it, and then the broker choice (Redis, SQS, Kafka) belongs to the app.
