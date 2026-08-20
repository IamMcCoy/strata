# 0007. 재귀의 트리거는 Tool, 메커니즘은 runtime.spawn_agent — Tool은 ToolEnv로 Runtime에 접근한다

- 상태: Accepted
- 날짜: 2026-08-21
- 대체: [0001](0001-rlm-as-recursive-strategy.md)의 "Tool vs Strategy" 이분법

## Context

ADR-0001은 "RLM을 Tool로 구현하면 재귀가 Runtime 통제 밖에서 일어난다"는 이유로
RecursiveStrategy를 택했다. 그러나 실제 RLM의 재귀(`llm_query`)는 모델이 tool call로
한 번씩 부르는 것이 아니라 **REPL 코드 안에서 함수로** 호출된다
(`for chunk in chunks: answers.append(llm_query(chunk, q))`). 모델은 거대 문맥을 볼 수
없으므로 "tool call 하나당 child 하나, 조각은 인자로 인라인" 방식으로는 분할 정복이
성립하지 않는다. 즉 트리거는 Tool(REPL) 쪽에 있어야 하는데, 기존 `Tool.execute(**kwargs)`는
Runtime에 접근할 길이 없어 Strategy가 tool call을 가로채는 우회(`_dispatch`)가 필요했고,
사용자도 Runtime을 쓰는 Tool(spawn, memory, REPL)을 만들 수 없었다.

## Decision

- **모든 Tool은 `execute(self, env: ToolEnv, **kwargs)`** 로 호출된다.
  `ToolEnv(context, runtime)`는 호출한 agent의 Context와 run의 Runtime이다.
  대부분의 Tool은 무시하고, Runtime primitive가 필요한 Tool만 사용한다.
- 재귀의 **트리거는 Tool**이다 — `SpawnAgentTool`(위임형, 모델이 직접 호출)과
  `PythonTool`의 `llm_query`(RLM형, 코드에서 호출). 둘 다 **메커니즘은
  `env.runtime.spawn_agent()`** 하나로 수렴하므로 한도 검사·Execution Tree 등록·계약 반환은
  여전히 Runtime 안에서 일어난다. ADR-0001의 우려("Tool이면 통제 밖")는 이 경로로 해소된다.
- Strategy의 tool call 가로채기는 없앤다. RecursiveStrategy = ReAct + `SpawnAgentTool` 광고,
  RLMStrategy = ReAct + `PythonTool` 광고 + 환경 설명 지시.

## Consequences

- (+) Tool이 Runtime의 1급 확장 지점이 된다 — spawn, REPL, memory 접근 Tool을 사용자가 만들 수 있다.
- (+) RLM의 "코드 루프 안에서 재귀" 패턴이 표현 가능해지고, 결과를 변수에 모으는 패턴도 자연스럽다.
- (+) Strategy 구현이 단순해진다(가로채기·가상 tool 개념 제거).
- (−) 단순 Tool도 쓰지 않는 `env` 인자를 받는다. 명시성을 택한 비용이다(시그니처 검사 같은 마법 없음).
- (−) Strategy가 자체 tool을 광고하면 `runtime.execute_tool(..., tools=)`에 그 매핑을 같이 넘겨야 한다.
