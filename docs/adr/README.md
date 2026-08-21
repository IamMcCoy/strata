# Architecture Decision Records

핵심 설계 결정과 그 근거의 기록. 결정이 바뀌면 새 ADR로 대체(supersede)하고,
기존 ADR은 삭제하지 않고 상태만 갱신한다.

## 목록

| # | 제목 | 상태 |
|---|---|---|
| [0001](0001-rlm-as-recursive-strategy.md) | RLM은 Tool이 아니라 Recursive Strategy로 구현한다 | Superseded by 0007 |
| [0002](0002-context-memory-separation.md) | Context와 Memory를 분리한다 | Accepted |
| [0003](0003-strategy-as-first-class-abstraction.md) | Strategy를 독립적인 실행 abstraction으로 만든다 | Accepted |
| [0004](0004-child-spawn-via-runtime.md) | Child Agent 생성은 runtime.spawn_agent()를 경유한다 | Accepted |
| [0005](0005-execution-tree-in-memory-first.md) | Execution Tree는 In-Memory로 시작한다 | Accepted |
| [0006](0006-runtime-per-run.md) | Runtime은 run당 하나이며 Agent.run이 유일한 진입점이다 | Accepted |
| [0007](0007-spawn-trigger-is-a-tool.md) | 재귀의 트리거는 Tool, 메커니즘은 runtime.spawn_agent — Tool은 ToolEnv로 Runtime에 접근한다 | Accepted |
| [0008](0008-all-primitives-through-runtime.md) | LLM 호출을 포함한 세 primitive는 모두 Runtime을 경유한다 (runtime.generate) | Accepted |
| [0009](0009-strategy-prompt-seam-and-model-params.md) | 패턴 지시는 Strategy.prompt(고정)+environment(동적), 모델 파라미터 우선순위(Strategy > Provider)는 Runtime.generate 한 줄 | Accepted |

## 템플릿

```markdown
# NNNN. 제목 (결정을 한 문장으로)

- 상태: Proposed | Accepted | Superseded by NNNN
- 날짜: YYYY-MM-DD

## Context
결정이 필요했던 배경과 제약.

## Decision
무엇을 하기로 했는가.

## Consequences
이 결정으로 얻는 것과 감수하는 것.
```
