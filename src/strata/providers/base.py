from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field

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
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        **kwargs,
    ) -> ModelResponse: ...
