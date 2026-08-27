# Strata Documentation

> Strata — A composable runtime for agentic systems.

## 읽는 순서

1. **[프로젝트 개요](overview/project-overview.md)** — Strata가 무엇이고, 무엇이 아닌지
2. **[RLM 배경](overview/rlm-background.md)** — 이 프로젝트의 출발점이 된 Recursive Language Models 방법론
3. **[Agentic Patterns 배경](overview/agentic-patterns-background.md)** — ReAct / Reflection / Plan&Execute / Router / Debate / Self-Consistency / Multi-Agent
4. **[아키텍처](architecture/architecture.md)** — 전체 구조, 컴포넌트 책임, 실행 흐름
5. **설계 문서**
   - [Core Abstractions](design/abstractions.md) — Provider / Tool / Memory / Context / Agent
   - [Strategies](design/strategies.md) — ReAct / Recursive(RLM) / Reflection / Composition
   - [Runtime](design/runtime.md) — Execution Tree / Budget / Events / Registry
6. **[ADR](adr/README.md)** — 핵심 설계 결정과 그 근거
7. **[로드맵](roadmap.md)** — Phase 1–9 구현 우선순위와 완료 기준
8. **[기여 가이드](CONTRIBUTING.md)** — 개발 환경(uv, Python 3.12), Git Flow, 코드 스타일

## 디렉토리 구성

| 디렉토리 | 내용 |
|---|---|
| `overview/` | 프로젝트 정의와 배경 지식. 처음 온 사람이 읽는 곳 |
| `architecture/` | 전체 구조와 컴포넌트 간 관계. 코드를 읽기 전 지도 |
| `design/` | 각 abstraction의 인터페이스와 동작 설계. 구현의 기준 |
| `adr/` | Architecture Decision Records. "왜 이렇게 했는가"의 기록 |
| `roadmap.md` | 구현 순서와 각 단계의 완료 기준 |
