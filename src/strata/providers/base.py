from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from types import MappingProxyType
from typing import Any

from strata.tools.base import Tool


class ProviderError(Exception):
    """LLM 인프라 오류 — Provider가 SDK 예외를 이걸로 번역한다 (ADR-0013).

    코어가 `openai`/`anthropic`을 import하지 않고도 **인프라 오류와 프로그래밍 오류를**
    가르기 위한 것이다. 429·5xx·타임아웃·연결 끊김·인증 실패는 내 코드의 버그가 아니므로
    run을 폭발시키지 않고 지금까지의 답과 함께 `status='failed'` 계약으로 끝낸다.
    반면 Strategy의 TypeError 같은 프로그래밍 오류는 그대로 전파된다 — 사용자가 봐야 한다.

    벤더 번역이 Provider의 책임인 것은 usage 표준 키·메시지 형식과 같은 이유다.
    """


@dataclass
class ToolCall:
    """모델이 요청한 tool 호출. Provider가 자사 형식을 이 형태로 통일한다."""

    name: str
    arguments: dict
    id: str | None = None
    # 코어가 해석하지 않고 그대로 왕복시키는 벤더 전용 상태. 의미는 Provider만 안다.
    # 예: Gemini 3.x는 function_call part의 thought_signature를 다음 턴에 돌려받아야 한다.
    # messages에 실려 앱의 저장소를 왕복하므로 **JSON 직렬화 가능한 값만** 넣는다 (ADR-0010).
    provider_state: dict = field(default_factory=dict)


@dataclass
class ModelResponse:
    """Provider별 응답을 통일하는 값 객체.

    usage 표준 키: input_tokens / output_tokens / total_tokens.
    자사 형식을 이 키로 변환하는 책임은 Provider 구현에 있다 — token budget 집계의 전제.

    reasoning은 사고 모드(thinking/reasoning)의 사고 과정 원문이다. 답이 아니라 **진단용**이다 —
    사고가 실제로 켜졌는지는 이것 말고 확인할 방법이 없다(끄면 None, 켜면 문자열).
    벤더 필드가 제각각이라(OpenAI compat `reasoning_content`, Anthropic thinking 블록,
    Gemini thought part) 여기서 하나로 모은다. text에 섞지 않고, messages에 되싣지도 않는다 —
    다음 턴에 돌려주면 벤더가 거절하거나 컨텍스트만 불린다.
    """

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw: object = None
    reasoning: str | None = None


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
        on_delta: Callable[[str], None] | None = None,
        **kwargs,
    ) -> ModelResponse: ...
    """on_delta를 주면 텍스트 조각이 도착하는 대로 호출한다. **반환값은 그래도 완결된
    ModelResponse다** — 스트리밍은 부수 채널이지 계약이 아니다 (ADR-0012).

    덕분에 Strategy는 스트리밍을 몰라도 되고, 한도·usage 집계가 한 경로로 유지된다.
    on_delta는 동기 콜백이다: await하면 실행이 소비자 속도에 묶인다. 앱은 큐에 밀어넣는다.
    execution_id는 Runtime이 붙인다 — Provider는 실행 트리를 모른다.
    """
