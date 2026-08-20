# RLM(Recursive Language Models) 배경

Strata의 Recursive Strategy 설계에 영감을 준 RLM 방법론을 정리한다.
Strata 설계에 직접 영향을 준 부분 중심으로 요약하며, 벤치마크·실험 세부는 생략한다.

## 핵심 아이디어 — 문맥을 "환경"으로 본다

일반적인 LLM 호출이 `Completion(Prompt + Context)` 형태라면, RLM은
`RLM(Prompt, Environment(Context))` 형태를 띤다.

- 환경(Environment)은 구체적으로 **Python REPL 상태**다. 거대한 문서·데이터는
  REPL 안의 변수(예: `ctx`)로 로드된다.
- 이 변수는 너무 커서 모델이 직접 읽을 수 없다. 대신 모델은 **변수에 접근하는 코드를
  생성·실행하여 결과를 관찰한다.** (`print(len(ctx))`, `print(ctx[:100])`, 정규표현식 필터링 등)
- 즉 모델은 문맥을 "읽어야 할 텍스트"가 아니라 **"프로그래밍 가능한 환경 변수"**로 다룬다.

Root LM은 전형적인 Agentic Loop를 따른다: 실행 기록(Trace)을 바탕으로 행동(코드 블록)을
결정 → 인터프리터에서 실행 → 관찰(Observation)을 프롬프트에 추가 → `FINAL(answer)`까지 반복.
데이터를 읽는 것을 넘어 가공·분석 코드(정규표현식, 통계)를 작성할 수 있다는 점이
RLM을 단순 검색기가 아닌 **추론 엔진**으로 만든다.

## 재귀 호출 — `llm_query`

RLM이라는 이름의 유래. Root LM이 사용할 수 있는 가장 강력한 도구는 자기 자신을 호출하는
함수 `llm_query(sub_context, sub_instruction)`이다.

- 문맥의 특정 부분에 깊은 이해가 필요하면 해당 조각과 지시사항을 인자로 하위 호출을 만든다.
- 하위 모델은 **자신만의 독립적인 REPL 환경과 문맥**을 할당받아 새로운 RLM 인스턴스로
  동작하고, 필요하면 또다시 자신을 호출할 수 있다.
- POSIX `fork()`와 유사하게 각 호출이 독립적인 Context Window를 가지므로,
  전체 시스템의 문맥 한계가 사실상 사라진다.

## 재귀 제어 — 종료 조건과 비용

재귀 알고리즘의 숙제인 종료 조건(Base Case)을 위해 다음 안전장치가 필요하다:

1. **최대 재귀 깊이(Max Recursion Depth)** — 일정 깊이 이상 하위 호출 금지.
   깊이에 따라 다른 모델을 쓰는 전략도 가능(말단은 가벼운 모델로 요약만).
2. **토큰 예산(Token Budget)** — 총 토큰을 설정하고 소진 시 강제 종료 또는 현재 결과 반환.
3. **명시적 종료 신호** — 시스템 메시지에 "충분히 찾았다면 `FINAL(답변)`을 출력하라"를
   포함하고, 출력에서 `FINAL` 감지 시 즉시 루프 탈출.

## 관찰된 창발적(Emergent) 행동 4가지

파인 튜닝 없이 추론 전략 변경만으로 나타난 패턴:

1. **코드 실행 기반 정보 필터링** — 무작정 읽는 대신 정규표현식으로 관련 부분만 발췌하고,
   모델의 사전 지식으로 프롬프트에 없는 연관 키워드까지 추론해 검색.
2. **분할 후 재귀 하위 호출 (Divide & Conquer)** — 파일/챕터 단위로 Chunking하고
   각 조각에 sub-task를 만들어 재귀 호출, 단서를 변수에 모아 최종 추론.
3. **작은 문맥으로 답변 검증** — 답 도출 후 검증에 필요한 핵심 조각만 하위 모델에 넘겨
   확인. Context Rot을 방지하고 정확도를 높인다. (단, 과잉 검증으로 오답에 이르는
   부작용 사례도 관찰됨)
4. **변수를 통한 긴 출력 생성** — 하위 모델들의 부분 답변을 리스트 변수에 모아
  `join`으로 합쳐, 출력 토큰 제한을 사실상 무력화.

> 참고: 원 연구는 S-NIAH, BrowseComp-Plus, OOLONG(-Pairs), LongBench-v2 CodeQA 등
> 복잡도 스케일링이 서로 다른 벤치마크에서 GPT-5·Qwen3-Coder 기반으로 검증했다.
> 세부 실험 설계는 원 논문 참조.

## 한계 → Strata 설계에의 시사점

| RLM의 한계 | Strata 설계 반영 |
|---|---|
| 모든 재귀 호출이 동기식(Synchronous)이라 실행 시간이 길어짐 | Runtime의 `spawn_agent`를 async 기반으로 설계하고, 향후 병렬 child 실행을 지원할 수 있도록 abstraction 유지 ([runtime 설계](../design/runtime.md)) |
| 모델별 행동 편차(과잉 분할, 수천 번의 불필요한 호출) | `max_depth` / `max_children` / `max_iterations` / `token_budget` 을 Runtime 차원에서 강제 |
| RLM 로직이 특정 구현(REPL + llm_query)에 고착 | RLM을 하나의 Strategy로 일반화 — REPL은 Tool, 재귀는 `runtime.spawn_agent()`, 예산은 RuntimeConfig ([ADR-0001](../adr/0001-rlm-as-recursive-strategy.md)) |

즉 Strata 관점에서 RLM은:

```text
RLM = RLMStrategy(ReAct loop + PythonTool REPL + llm_query → runtime.spawn_agent)
      + Runtime의 실행 제어(depth/budget) + Execution Tree
```

`Environment(Context)`의 객체화 — 거대 데이터를 변수로 담고 코드로만 접근하는
구조 — 는 `Context.variables` + REPL Tool의 조합으로 표현한다. REPL 네임스페이스가
`Context.variables` 그 자체이고, `llm_query(prompt, context=chunk)`는 child의
`variables['context']`에 조각만 넘긴다
([abstractions.md의 문맥의 객체화](../design/abstractions.md#문맥의-객체화--environmentcontext),
[strategies.md의 RLM](../design/strategies.md#rlm-strategy--문맥을-환경으로-다루는-재귀)).
재귀의 트리거가 REPL 함수(Tool)인 이유는 [ADR-0007](../adr/0007-spawn-trigger-is-a-tool.md).

로 분해된다. RLM은 프레임워크가 지원하는 하나의 패턴이며, 같은 기반 위에서
ReAct·Reflection 등 다른 패턴도 동일하게 구현된다.
