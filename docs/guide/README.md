# Strata 사용 가이드

[English](en/README.md) | **한국어**

각 문서는 **혼자 읽어도 완결된다.** 다른 문서를 먼저 읽어야 이해되는 곳은 없다.

| | |
|---|---|
| [1. Agent](01-agent.md) | 조립과 실행. `Agent.run` 하나가 진입점이다 |
| [2. Provider](02-providers.md) | 모델 붙이기 — OpenAI·Claude·Gemini·vLLM·Ollama, 스트리밍, 오류, 폴백 |
| [3. Tool](03-tools.md) | 도구 만들기. `execute(self, env, **kwargs)` 하나만 구현한다 |
| [4. Memory](04-memory.md) | 실행 사이에 남는 사실. 저장은 명시적, 조회는 자동 |
| [5. 멀티턴](05-conversation.md) | 대화 이력은 앱이 갖는다. 길어지면 잘라 넣는다 |
| [6. Strategy](06-strategies.md) | 실행 패턴 5종과 커스텀 전략 |
| [7. 한도·취소·관찰](07-limits.md) | 폭주를 막는 배관 |

클래스·함수·파라미터의 기계적 목록은 손으로 쓰지 않는다 — 파라미터가 바뀌면 문서가
거짓말이 되고 아무도 안 고친다. 코드의 docstring에서 생성한다:

```bash
make docs      # → docs/api/index.html (git에 넣지 않는 생성물)
```

| | 이 가이드 | `docs/api/` |
|---|---|---|
| 답하는 것 | "멀티턴은 어떻게 하나" | "`RouterStrategy`의 인자가 뭐지" |
| 만드는 법 | 손으로 | `make docs` |

## 설치

```bash
uv add strata               # 코어는 런타임 의존성 0개
uv add 'strata[openai]'     # 프로바이더는 extra: openai / anthropic / gemini / redis / all
```

Python 3.12 이상.

## 5분

```python
import asyncio
from strata import Agent, OpenAIProvider, ReActStrategy, Tool


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
    result = await agent.run('add tool로 123456 + 654321을 계산해줘')
    print(result.status, result.result)


asyncio.run(main())
```

세 가지만 기억하면 된다:

- **등록만 한다** — Provider·Tool·Memory를 인자로 넘기면 끝이다. 배선은 없다.
- **진입점은 `run` 하나다** — 스트리밍이든 멀티턴이든 거대 입력이든 전부 `run`의 인자다.
- **실패는 예외가 아니라 결과다** — 한도 초과·모델 오류는 `result.status`로 돌아온다.

동작하는 예제가 [`examples/`](../../examples)에 있고 **API 키 없이** 전부 돌아간다.
