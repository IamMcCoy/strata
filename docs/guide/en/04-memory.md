# 4. Memory

**English** | [한국어](../04-memory.md)

**Facts that persist between runs.** This is where today's run learns what yesterday's learned.

It is not conversation history — that's [5. Multi-turn](05-conversation.md). The difference:

| | Memory | Conversation history |
|---|---|---|
| What | Facts ("the user uses uv") | Verbatim text ("what did I say earlier?") |
| Order | None | Yes (order is part of the meaning) |
| Stored | Explicitly, by the model | Accumulates automatically |
| Owned by | The Memory implementation | The app |

## Three implementations

```python
from strata import InMemory, SQLiteMemory, RedisMemory

InMemory()                                          # dev/testing. Gone when the process dies
SQLiteMemory('memory.db', namespace='user:42')      # persistent. stdlib sqlite3, so zero dependencies
RedisMemory(client=redis_client, namespace='u:42')  # when workers are spread across hosts
```

`RedisMemory` takes the client by **injection** — strata never imports `redis`. Connection
settings, pool size, and auth reuse whatever the app already has.

`InMemory` is process-local. With multiple workers, **each worker's memory diverges.**

### Scope is separated by instance

There is no `retrieve(query, user_id=...)` argument. You separate instances instead:

```python
alice = SQLiteMemory('memory.db', namespace='user:alice')
bob   = SQLiteMemory('memory.db', namespace='user:bob')
# same file, invisible to each other
```

This makes the "forgot to pass user_id and read someone else's memory" accident
structurally impossible.

## Storing is explicit, retrieval is automatic

This asymmetry is the heart of the design.

```python
agent = Agent(
    provider=...,
    strategy=ReActStrategy(),
    memory=SQLiteMemory('memory.db', namespace='user:42'),   # ← turns on retrieval
    tools=[MemoryTool()],                                     # ← turns on storing
)
```

**Retrieval happens automatically on every `run`.** It searches with the task string and
appends the top items to the system instructions:

```
## What you remember from earlier runs
- The user uses uv
- Never deploy on Fridays
```

If you told the model "go look up your memories", some turns wouldn't — and then it
answers unaware even though the memory is right there. That's why it's automatic.

**Storing requires the model to explicitly call `remember`.** If it were automatic,
everything would be stored, and hundreds of "sure, got it" would bury the real memories.
Being frugal with storage is how you protect retrieval quality.

```python
# the two can be given separately
Agent(..., memory=mem)                        # read-only — just inject an app-managed profile
Agent(..., memory=mem, tools=[MemoryTool()])  # read and write
```

## Putting things in and taking them out yourself

```python
from strata import MemoryItem

await mem.store(MemoryItem(content='This user belongs to the R&D Center'))
await mem.store(MemoryItem(content='Deployments are approved by the team lead', type='procedural'))

items = await mem.retrieve('deployment procedure', limit=5)
await mem.delete(items[0].id)
```

`MemoryItem`:

```python
MemoryItem(
    content,                 # a self-contained fact in one sentence
    type='semantic',         # semantic | episodic | procedural — the core doesn't interpret it
    id=None,                 # store fills it in
    metadata={},             # free-form dict
)
```

Information that must survive should be **`store`d directly by the app**. Whether the
model calls `remember` is a judgment call and not guaranteed.

## What gets retrieved

Scoring is BM25 — it weighs frequency, document length, and term rarity together. It
counts **substrings**, not tokens, because Korean is agglutinative and word-level
comparison misses almost everything (`'uv를' != 'uv'`).

All three implementations use **the same scoring function**. Swapping the storage backend
must not change the judgment of "what is relevant".

Three limitations, accepted knowingly:

- **It is not semantic search.** `'payment failed'` won't find `'purchase error'`. If
  synonyms matter, plug in an embedding-based implementation behind the same `Memory`
  interface.
- **It is a full scan.** At 20,000 items, one lookup takes tens of ms. It hurts once you
  have far more than that.
- **It has no notion of time.** A fact from 5 seconds ago and one from a year ago are
  equals. If "used to use vim, now uses vscode" are both stored, there's no telling which
  wins. Conflicting memories must be cleaned up with `delete`.

## Building your own

```python
from strata import Memory, MemoryItem
from strata.memory.base import rank        # share the scoring function and results stay consistent

class MyMemory(Memory):
    async def store(self, item: MemoryItem) -> None: ...
    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        return rank(await self._all(), query, limit)
    async def delete(self, memory_id: str) -> None: ...
```
