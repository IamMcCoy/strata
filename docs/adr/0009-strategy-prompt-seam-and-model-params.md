# 0009. 패턴 지시는 Strategy.prompt + environment(), 모델 파라미터 우선순위는 Runtime.generate 한 줄

- 상태: Accepted
- 날짜: 2026-08-21

## Context
각 Strategy는 모델에게 자기 실행 패턴(tool 규율·종료 규약·위임/REPL 규칙)을 설명해야 하고, 사용자는
그 지시와 샘플링 파라미터(temperature 등)를 덮어쓸 수 있어야 한다. 두 가지를 어디에 두느냐가 문제였다:

- 지시: Agent에 전부 두면 Agent가 Strategy 내부(RLM의 변수 목록 등)를 알아야 하고 Router처럼 Strategy가
  여럿이면 "어느 전략의 지시인가"가 깨진다. 모듈 공용 `prompts.py`는 읽을 때 파일을 건너뛰게 한다.
  `.format()` 템플릿은 전략 하나(RLM)의 구현 디테일을 전체 인터페이스에 새긴다.
- 파라미터: `RuntimeConfig`는 Runtime이 *강제*하는 한도의 자리다. Provider마다 지원 키가 다르다
  (`top_k`는 Anthropic만, reasoning 모델은 `temperature` 거부) — 코어가 스키마를 가질 수 없다.

## Decision
1. **system = `Context.instructions`(사용자, child 상속) + `Strategy.prompt`(패턴, 고정 텍스트) +
   `Strategy.environment(context)`(호출 시점 상태)** — `ReActStrategy.instructions()` 한 곳에서 조립해
   `runtime.generate(instructions=)`로 넘긴다. `prompt`는 클래스 속성이며 `REACT_PROMPT` /
   `RECURSIVE_PROMPT = REACT_PROMPT + …` / `RLM_PROMPT`를 export한다. 변하는 내용(RLM 변수 목록, 향후
   Reflection의 이전 초안)은 prompt에 구멍을 뚫지 않고 `environment()`로 붙인다 — export 상수 == 모델이
   보는 텍스트.
2. **덮어쓰기는 명시 인자**: `Strategy(prompt=, model_params=)` → 서브클래스 속성 → `instructions()`
   오버라이드. `prompt=''`로 끈다. `**kwargs` 만능 입구는 두지 않는다(오타가 조용히 삼켜짐).
3. **모델 파라미터는 코어가 해석하지 않는 dict**. 입구는 `Provider.model_params`(배포 기본값)와
   `Strategy.model_params`(패턴별). 합치는 곳은 `Runtime.generate` 한 줄 —
   `provider.generate(messages, tools, **{**provider.model_params, **kwargs})` — 이므로 우선순위
   (호출/Strategy > Provider)는 거기에만 있고 Provider 구현은 받은 kwargs를 그대로 싣는다(ADR-0008의 연장).
   `RuntimeConfig`에는 두지 않는다.

## Consequences
- 의도된 동작 변경: 사용자 지시가 없어도 ReAct 계열은 패턴 지시를 system으로 보낸다. 끄려면 `prompt=''`.
- 새 Provider(Anthropic 등)는 `model_params`를 인스턴스 속성으로 저장만 하면 된다.
- 알고 받아들인 비용: RLM 변수 목록이 system 안에 있어 변수가 바뀌는 턴마다 prompt cache 접두가 깨진다
  (기존 동작과 동일). tool이 0개인 ReAct에도 tool 규율이 실린다(`prompt=''`로 끔).
