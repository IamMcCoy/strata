# Strata

> A composable runtime for agentic systems.

**Strata**는 다양한 Agentic Pattern(ReAct, Recursive/RLM, Reflection, …)을
하나의 Runtime 위에서 구현하고 조합할 수 있도록 하는 확장형 Agent Execution Framework다.
Provider, Tool, Memory, Context, Strategy, Execution을 독립적인 primitive로 추상화하고,
Runtime이 이들을 연결·실행·관찰한다.

```python
agent = Agent(
    provider=provider,
    strategy=RecursiveStrategy(max_depth=5),
    tools=[WebSearchTool(), PythonTool()],
    memory=memory,
)

result = await agent.run("복잡한 문제를 분석하고 결과를 도출해줘")
```

같은 Agent에서 `strategy=` 만 교체하면 실행 패턴이 바뀐다.

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

Phase 1 — Core Abstraction. 인터페이스 뼈대만 존재하며 실행 로직은 없다.
구현 순서는 [로드맵](docs/roadmap.md) 참조.

## 개발 환경

Python 3.12 + [uv](https://docs.astral.sh/uv/). 브랜치 전략과 코드 스타일은
[기여 가이드](docs/CONTRIBUTING.md) 참조.

```bash
uv sync            # .venv 생성 + 의존성 설치
uv run pytest      # 테스트
```
