# 0014. 전략이 한도를 제안하고 Runtime이 강제한다 — merge는 Agent.run 한 줄

- 상태: Accepted
- 날짜: 2026-08-27

## Context
`RuntimeConfig`는 실행 한도의 자리이고 강제는 Runtime이 한다(ADR-0004). 그런데 어떤 한도의
**적정값은 전략만 안다**:

- `ReflectionStrategy(rounds=4)`는 child가 `1 + rounds*2 = 9`개 필요하다. 기본 `max_children=8`
  아래에서는 2라운드 만에 `budget_exceeded`로 조용히 잘렸다 — 사용자가 공식을 스스로 알아내
  `RuntimeConfig(max_children=9)`를 따로 적어야 고쳐지는 상태였다.
- `max_iterations`는 ReAct 계열의 루프 상한으로 읽히지만 설정은 전략과 떨어진 자리에 있어,
  전략을 바꿀 때 같이 옮겨야 할 값이 눈에 띄지 않는다.

한도를 Strategy로 **옮기는** 선택지도 있었다. 그러면 Custom Strategy가 `runtime.generate`를
무한히 부를 수 있게 되고 "한도를 몰라도 Runtime이 막아 준다"는 확장점의 안전 속성이 사라진다.

## Decision
1. **`Strategy.limits`** — 전략이 `RuntimeConfig` 필드 이름으로 한도를 *제안*한다.
   생성 시점에 받는다: `ReActStrategy(max_iterations=10)`, `RecursiveStrategy(max_depth=2)`,
   `ReflectionStrategy(rounds=4)`(→ `{'max_children': 9}`를 스스로 계산).
2. **강제는 그대로 Runtime** — 제안은 값의 출처만 바꾼다. 검사 지점(`generate`/`spawn_agent`)도,
   초과가 예외가 아니라 계약이라는 것도 그대로다. ADR-0004는 유효하다.
3. **우선순위는 `Agent.run`의 `resolve_limits` 한 줄에만** — 사용자가 `RuntimeConfig`에 명시한
   값 > `Strategy.limits` > `RuntimeConfig` 기본값. `model_params`(Strategy > Provider 기본값,
   merge는 `Runtime.generate` 한 줄, ADR-0009)와 같은 이음매다.
4. **root 전략에서 한 번만 merge한다** — 한도는 run 전체가 공유하므로 child가 다시 올리지 않는다.
5. **ADR-0009의 "`**kwargs` 만능 입구는 두지 않는다"에 대한 예외**다. 그 결정의 근거는
   "오타가 조용히 삼켜짐"이었고, 여기서는 `validate_limits`가 생성 시점에 이름을 `RuntimeConfig`
   필드와 대조해 `TypeError`를 낸다 — `ReActStrategy(max_iteration=3)`은 run까지 가지 않는다.
   근거가 해소되었으므로 한도에 한해 열어 둔다. `model_params`는 코어가 스키마를 가질 수 없어
   여전히 명시 인자다.

## Consequences
- `ReflectionStrategy(rounds=4)`가 별도 설정 없이 4라운드를 돈다
  (`tests/test_strategy_limits.py::test_reflection_rounds_four_now_completes`).
- 전략이 기본값보다 **높은** 한도를 제안할 수 있다 — "네가 설정한 동작을 하려면 구조적으로
  이만큼 필요하다"는 선언이고, 사용자가 `RuntimeConfig`로 명시하면 언제나 사용자가 이긴다.
  한도는 run 전체 공유이므로 중첩된 worker(예: `worker=RecursiveStrategy()`)에도 같은 값이 적용된다.
- 알고 받아들인 비용: "사용자가 명시했는가"를 `RuntimeConfig()` 기본값과의 비교로 판단한다.
  사용자가 기본값과 똑같은 값을 명시하면 전략이 이긴다. 구분해야 할 날이 오면 필드 기본값을
  `None`으로 바꾸고 해석을 뒤로 미뤄야 한다 — 그때까지는 한 줄로 둔다.
- `Strategy` base에 `__init__`이 생겼다. 부르지 않는 기존 서브클래스는 클래스 기본값
  (읽기 전용 `MappingProxyType({})`)을 그대로 쓰므로 동작이 바뀌지 않는다.
