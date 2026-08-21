from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from types import MappingProxyType
from typing import Any

from strata.tools.base import Tool


@dataclass
class ToolCall:
    """모델이 요청한 tool 호출. Provider가 자사 형식을 이 형태로 통일한다."""

    name: str
    arguments: dict
    id: str | None = None


@dataclass
class ModelResponse:
    """Provider별 응답을 통일하는 값 객체.

    usage 표준 키: input_tokens / output_tokens / total_tokens.
    자사 형식을 이 키로 변환하는 책임은 Provider 구현에 있다 — token budget 집계의 전제.
    """

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw: object = None


class Provider(ABC):
    """LLM 통신 추상화. Strategy는 이 인터페이스만 바라본다.

    Tool.input_schema(JSON Schema)를 자사 tool 형식으로 변환하는 책임도 Provider에 있다.
    model_params: 이 Provider로 나가는 모든 요청의 기본 샘플링 파라미터(temperature 등). 코어는 해석하지
    않는다. 합치는 곳은 Runtime.generate 한 곳 — `{**provider.model_params, **호출 kwargs}` — 이므로
    구현은 받은 kwargs를 요청에 그대로 실으면 된다. 구현은 인스턴스에서 dict(...)로 설정한다.
    """

    # 클래스 기본값은 읽기 전용 — 모든 Provider가 공유하므로 실수로 고치면 누출 대신 TypeError. 설정은 인스턴스 속성으로.
    model_params: Mapping[str, Any] = MappingProxyType({})

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        **kwargs,
    ) -> ModelResponse: ...
