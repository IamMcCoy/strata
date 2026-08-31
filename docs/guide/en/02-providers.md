# 2. Provider

**English** | [한국어](../02-providers.md)

Where the model plugs in. The core imports no SDK, so install only what you use as extras.

```bash
uv add 'strata[openai]'      # OpenAI, plus every OpenAI-compatible endpoint
uv add 'strata[anthropic]'   # Claude
uv add 'strata[gemini]'      # Gemini native
uv add 'strata[all]'
```

## Four providers + the compatible family

```python
from strata.providers import OpenAIProvider, AnthropicProvider, GeminiProvider

OpenAIProvider(model='gpt-4o-mini')                       # uses the OPENAI_API_KEY environment variable
AnthropicProvider(model='claude-sonnet-5', max_tokens=4096)
GeminiProvider(model='gemini-3.5-flash-lite')
```

**vLLM, Ollama, and OpenRouter are not separate classes.** They are OpenAI-compatible APIs,
so it's the same code with only `base_url` changed:

```python
OpenAIProvider(model='Gemma4-12B-it', api_key='not-needed',
               base_url='http://192.168.1.70:8000/v1')          # vLLM
OpenAIProvider(model='llama3.1', api_key='not-needed',
               base_url='http://localhost:11434/v1')            # Ollama
OpenAIProvider(model='anthropic/claude-sonnet-4', api_key=OPENROUTER_KEY,
               base_url='https://openrouter.ai/api/v1')         # OpenRouter
```

Claude and Gemini get separate implementations not for performance but because their
**message structures are fundamentally different** — for Claude, system is a top-level parameter
and tool calls/results are content blocks; for Gemini, system is config, the assistant is
`role='model'`, and tools are parts.

### Using tools on vLLM

The server must be started with `--enable-auto-tool-choice --tool-call-parser <parser>`. Without
it, you get a 400 the moment you pass a tool. **It's not a code problem — it's a server launch option.**

## Common parameters

```python
OpenAIProvider(
    model,                      # required
    api_key=None,               # falls back to the OPENAI_API_KEY environment variable
    base_url=None,              # compatible endpoint
    max_retries=2,              # SDK retries 429/5xx/connection errors with exponential backoff (3 attempts total)
    model_params=None,          # {'temperature': 0.2, ...} deployment defaults
    **client_kwargs,            # timeout etc. — passed straight to the SDK constructor
)
```

**Retries are left to the SDK.** The reason the core doesn't stack its own retry layer is that
backoff multiplies (3 × 3 = 9 attempts, and the waiting time even more). If you don't want to
lose an entire long recursive run to a single rate limit, raise `max_retries`. But the **total wait
time is roughly `max_retries × timeout`**, so set the two together.

The precedence for `model_params` is **Strategy > Provider**. Put deployment defaults on the
Provider, and give them to a strategy when only a specific pattern should differ:

```python
OpenAIProvider(model='gpt-4o-mini', model_params={'temperature': 0.7})   # default
ReActStrategy(model_params={'temperature': 0})                            # 0 for this strategy only
```

The core does not interpret this dict — it passes it straight to the SDK, because supported keys
differ by vendor (reasoning models reject `temperature`, and anthropic SDK 1.0 no longer accepts
`temperature`/`top_p`/`top_k` at all — they moved into `output_config`).

## Streaming

Give `Agent` an `on_delta` and it turns on. Strategy code changes not at all.

```python
agent = Agent(
    provider=OpenAIProvider(model='gpt-4o-mini'),
    strategy=ReActStrategy(),
    on_delta=lambda text, execution_id: print(text, end='', flush=True),
)
result = await agent.run(task)      # still returns a complete AgentResult
```

`execution_id` comes along, so in recursive execution you can tell **which agent's output** it is.
In a web server, push it into an SSE queue:

```python
on_delta=lambda text, execution_id: queue.put_nowait({'id': execution_id, 'text': text})
```

Caution: if a compatibility layer doesn't accept `stream_options: {include_usage: true}`,
**usage leaks as zero.** Then `token_budget` is silently disabled. After attaching a new endpoint,
check once:

```python
assert agent.runtime.usage['total_tokens'] > 0
```

## Thinking / reasoning mode

How you turn it on differs by vendor. The core does not interpret this dict, so put it in
`model_params` as-is:

```python
# vLLM — the SDK's create() has no **kwargs. Vendor extensions go through extra_body.
OpenAIProvider(
    base_url='http://localhost:8000/v1', model='Gemma4-12B-it',
    model_params={'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}},
)

OpenAIProvider(model='o4-mini', model_params={'reasoning_effort': 'high'})
AnthropicProvider(model='claude-sonnet-5', max_tokens=4096,
                  model_params={'thinking': {'type': 'enabled', 'budget_tokens': 2048}})
GeminiProvider(model='gemini-3.5-flash-lite', model_params={
    'thinking_config': types.ThinkingConfig(include_thoughts=True, thinking_budget=1024)})
```

**Passing the parameter does not mean it is on** — a server silently ignores keys it does not
know. Check in two places:

```python
result = await agent.run(task)
result.metadata.get('reasoning')   # ['thought 1', 'thought 2', ...] or None (off/unsupported)
agent.runtime.usage['reasoning_tokens']
```

`reasoning` is a list in `generate` call order — if ReAct calls tools three times, there are three
thoughts. In recursive runs a child's thoughts roll up to the root (one `Runtime` per run).

Vendors expose different things, so **the evidence splits in two** (measured):

| Provider | `metadata['reasoning']` | `usage['reasoning_tokens']` |
| --- | --- | --- |
| vLLM / DeepSeek | full text | (when present) |
| Claude | full text | — |
| Gemini | summary | ✅ |
| OpenAI (o-series) | **none** | ✅ |

Stock OpenAI **never** returns thinking text. A `None` there does not mean it is off — read
`reasoning_tokens` instead. Conversely vLLM reports `reasoning_tokens: 2` even with thinking off,
because of the empty `<think></think>` block — **the difference between off and on is the
evidence, not the absolute value** (measured on Gemma4-12B: 2 vs 422). `examples/thinking.py`
runs that comparison in one go.

Thinking never flows through `on_delta`; the app only receives answer chunks. Mixing them would
render thinking as the answer with no way back. The cost is that a longer thought means a longer
silence before the first chunk. The text arrives once, after the run, in `metadata['reasoning']`.

## Errors

Provider SDK exceptions are translated into `ProviderError` and returned via the **result contract**:

```python
result = await agent.run(task)
if result.status == 'failed' and result.metadata.get('reason') == 'provider_error':
    print(result.metadata['detail'])     # 'RateLimitError: ...'
    print(result.result)                 # the answer so far is still alive
```

Reaching this point means **the SDK's retries are already exhausted.** Don't call again
immediately — back off or move to another provider.

## Fallback

```python
from strata.providers import FallbackProvider

provider = FallbackProvider([
    OpenAIProvider(model='gpt-4o-mini'),
    AnthropicProvider(model='claude-sonnet-5'),
])
```

It tries from the front and moves to the next on `ProviderError`. Only when the last one fails
does the `ProviderError` propagate.

**Caution**: context overflow (`400 context_length_exceeded`) is also a `ProviderError`. This is an
error that never succeeds on retry, so the fallback fails identically on the next provider and only
burns money. If your input might be large, don't rely on fallback — do the trimming in
[5. Multi-turn](05-conversation.md) first.

## Writing your own

```python
from strata.providers import Provider, ModelResponse, ToolCall

class MyProvider(Provider):
    async def generate(self, messages, tools=None, **kwargs):
        # messages: [{'role': 'system'|'user'|'assistant'|'tool', 'content': ..., ...}]
        # tools:    list[Tool] — read .name / .description / .input_schema into the vendor format
        return ModelResponse(
            text='...',
            tool_calls=[ToolCall(name='add', arguments={'a': 1, 'b': 2}, id='call_1')],
            usage={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )
```

If you don't fill in `usage`, `token_budget` doesn't work. To support streaming, accept the
`on_delta` keyword and call it per chunk, but the return value must still be a complete
`ModelResponse`.
