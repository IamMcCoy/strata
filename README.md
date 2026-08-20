# Strata

> A composable runtime for agentic systems.

**Strata**는 다양한 Agentic Pattern(ReAct, Recursive/RLM, Reflection, …)을
하나의 Runtime 위에서 구현하고 조합할 수 있도록 하는 확장형 Agent Execution Framework다.
Provider, Tool, Memory, Context, Strategy, Execution을 독립적인 primitive로 추상화하고,
Runtime이 이들을 연결·실행·관찰한다.

```python
from strata import Agent, OpenAIProvider, RLMStrategy, RuntimeConfig

agent = Agent(
    provider=OpenAIProvider(model='gpt-4o-mini'),
    strategy=RLMStrategy(),             # ReActStrategy / RecursiveStrategy 로 교체 가능
    instructions='한국어로 간결하게 답하라.',
    config=RuntimeConfig(max_depth=3, token_budget=200_000),
)

# 거대 입력은 메시지가 아니라 변수 `context`로 들어간다 — 모델은 python tool로 조각내고
# llm_query로 child agent에 조각만 넘겨 결과를 모은다 (RLM).
result = await agent.run('이 문서의 모든 장의 핵심 숫자를 합산하라.', context=huge_document)
print(result.status, result.result)        # completed | failed | budget_exceeded
```

같은 Agent에서 `strategy=` 만 교체하면 실행 패턴이 바뀐다. 한도(depth/children/iterations/
token/timeout)는 Strategy가 아니라 Runtime이 강제하고, 초과 시 예외 대신 `budget_exceeded`
결과(지금까지의 답 포함)를 돌려준다. Tool은 `execute(self, env, **kwargs)` 하나만 구현한다.

## 설치

아직 PyPI에 배포하지 않았다 (배포명·라이선스 미정). git으로 직접 설치:

```bash
uv add git+https://github.com/IamMcCoy/strata.git
# 또는: pip install git+https://github.com/IamMcCoy/strata.git
```

설치 후 `import strata` 로 사용한다. 타입 힌트가 포함되어 있다(PEP 561, `py.typed`).

Provider SDK는 optional extra로 설치한다 (코어는 의존성 0):

```bash
uv add 'strata[openai] @ git+https://github.com/IamMcCoy/strata.git'
```

## 문서

- [문서 인덱스](docs/README.md) — 읽는 순서 안내
- [프로젝트 개요](docs/overview/project-overview.md)
- [아키텍처](docs/architecture/architecture.md)
- [ADR](docs/adr/README.md)
- [로드맵](docs/roadmap.md)
- [기여 가이드](docs/CONTRIBUTING.md) — Git Flow, 코드 스타일

## 상태

Phase 1~3·5 완료 — ReAct / Recursive / RLM Strategy, OpenAI Provider, Runtime 한도 전체.
다음은 Memory(Phase 4)와 Events(Phase 6). 구현 순서는 [로드맵](docs/roadmap.md) 참조.
예제: `examples/react.py`, `examples/recursive.py`, `examples/rlm.py`(fake provider),
`examples/react_openai.py`, `examples/rlm_openai.py`(실제 API).

## 개발 환경

Python 3.12 + [uv](https://docs.astral.sh/uv/). 브랜치 전략과 코드 스타일은
[기여 가이드](docs/CONTRIBUTING.md) 참조.

```bash
uv sync            # .venv 생성 + 의존성 설치
uv run pytest      # 테스트
```
