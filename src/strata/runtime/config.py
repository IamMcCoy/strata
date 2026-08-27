from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import replace
from typing import Any


@dataclass
class RuntimeConfig:
    """실행 한도. 강제는 Strategy가 아닌 Runtime의 책임 (ADR-0004).

    기본값은 Strategy가 `limits`로 제안할 수 있다 — 전략만 아는 공식이 있기 때문이다
    (Reflection의 child 수 = 1 + rounds*2). 우선순위는 `resolve_limits` 한 줄에만 있다 (ADR-0014).
    """

    max_depth: int = 5
    max_iterations: int = 30
    max_children: int = 8
    token_budget: int | None = None
    timeout: float | None = None  # 초 단위, run 전체 기준


_FIELD_NAMES = frozenset(field.name for field in fields(RuntimeConfig))
_DEFAULTS = RuntimeConfig()


def validate_limits(limits: Mapping[str, Any]) -> dict[str, Any]:
    """Strategy가 선언한 한도의 이름을 생성 시점에 검사한다 — 오타를 run까지 끌고 가지 않는다."""
    unknown = sorted(set(limits) - _FIELD_NAMES)
    if unknown:
        raise TypeError(f'unknown limit(s) {unknown}; known: {sorted(_FIELD_NAMES)}')
    return {name: value for name, value in limits.items() if value is not None}


def resolve_limits(config: RuntimeConfig, limits: Mapping[str, Any]) -> RuntimeConfig:
    """전략이 제안한 한도를 **사용자가 명시하지 않은 자리에만** 채운다.

    우선순위: 사용자가 RuntimeConfig에 명시한 값 > Strategy.limits > RuntimeConfig 기본값.
    model_params(Strategy > Provider 기본값)와 같은 이음매이고, merge는 여기 한 줄뿐이다.
    ponytail: "명시했는가"는 기본값과의 비교로 판단한다 — 사용자가 기본값과 똑같은 값을
    명시하면 전략이 이긴다. 그걸 구분해야 하면 필드 기본값을 None으로 바꾸고 해석을 미뤄야 한다.
    """
    fill = {
        name: value for name, value in limits.items()
        if getattr(config, name) == getattr(_DEFAULTS, name)
    }
    return replace(config, **fill) if fill else config
