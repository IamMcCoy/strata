from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from strata.providers.base import ModelResponse
from strata.providers.base import Provider
from strata.providers.base import ProviderError
from strata.tools.base import Tool

logger = logging.getLogger(__name__)


class FallbackProvider(Provider):
    """앞의 Provider가 인프라 오류로 실패하면 다음으로 넘어간다 (ADR-0013).

        Agent(provider=FallbackProvider([openai, claude]), ...)

    코어를 고치지 않는다 — Provider ABC만 구현하므로 어떤 Strategy와도 그대로 동작한다.
    벤더가 바뀌면 답의 품질도 바뀌므로 **사용자가 명시적으로** 선택해야 하는 일이다.

    `ProviderError`만 잡는다. 프로그래밍 오류에 폴백하면 같은 버그를 벤더 수만큼
    반복 실행할 뿐이다.

    **스트리밍 주의**: 이미 조각을 흘린 뒤 실패하면 폴백해도 텍스트가 중복 출력된다.
    그래서 **첫 델타가 나가기 전에 실패한 경우에만** 넘어가고, 그 뒤라면 그대로 올린다.
    """

    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError('FallbackProvider needs at least one provider')
        self.providers = providers

    @property
    def model_params(self) -> Any:  # type: ignore[override]
        """첫 Provider의 기본값을 쓴다 — merge는 Runtime.generate 한 곳이라는 규칙 유지."""
        return self.providers[0].model_params

    async def generate(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        on_delta: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        errors: list[str] = []
        for index, provider in enumerate(self.providers):
            streamed = False

            def sink(text: str, _provider=provider) -> None:
                nonlocal streamed
                streamed = True
                if on_delta is not None:
                    on_delta(text)

            try:
                return await provider.generate(
                    messages, tools=tools, on_delta=None if on_delta is None else sink, **kwargs,
                )
            except ProviderError as exc:
                if streamed:
                    # 이미 사용자에게 흘러간 텍스트가 있다 — 여기서 폴백하면 중복 출력된다
                    raise
                errors.append(f'{type(provider).__name__}: {exc}')
                logger.warning(
                    'provider.fallback %d/%d %s 실패 — 다음으로 넘어간다',
                    index + 1, len(self.providers), type(provider).__name__,
                )
        raise ProviderError('all providers failed — ' + ' | '.join(errors))
