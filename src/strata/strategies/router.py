from __future__ import annotations

import logging
from typing import Any

from strata.agent.context import Context
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy
from strata.tools.base import Tool
from strata.tools.base import ToolEnv

logger = logging.getLogger(__name__)

# 분류 호출의 지시. 사용자 지시(Context.instructions)는 일부러 빼고 이것만 보낸다 —
# "한국어로 답해라" 같은 지시는 어느 전략을 고를지와 무관하고 노이즈만 된다.
ROUTER_PROMPT = """\
You route a task to the execution strategy that fits it best.

Call the `route` tool exactly once with your choice, and nothing else. Do not attempt the task itself.
Pick by what the task needs, not by what sounds impressive: when nothing clearly calls for a
specialised strategy, choose the general-purpose one."""


class RouteTool(Tool):
    """분류를 free-text가 아니라 tool call로 받기 위한 tool. 실행되지 않는다.

    라우터는 `tool_calls[0].arguments['strategy']`만 읽는다. enum 스키마라 모델이 고를 수 있는
    값이 고정되고("아마 Reflection이 좋을 것 같은데 ReAct도…" 같은 답이 불가능해진다),
    이 저장소는 그 배관을 이미 갖고 있다.
    """

    name = 'route'

    def __init__(self, names: list[str], description: str):
        self.description = description
        self.input_schema = {
            'type': 'object',
            'properties': {
                'strategy': {'type': 'string', 'enum': names, 'description': 'The strategy to run'},
            },
            'required': ['strategy'],
        }

    async def execute(self, env: ToolEnv, **kwargs: Any) -> Any:
        # 도달하지 않는다 — 라우터가 generate의 반환만 읽고 execute_tool을 부르지 않는다.
        return kwargs.get('strategy', '')


class RouterStrategy(Strategy):
    """어느 전략이 이 과제에 맞는지 고르고, 고른 전략이 끝까지 푼다.

    supervisor(작업 분해·위임)가 아니라 **바깥 껍데기**다 — 문제를 "푸는" 패턴이 아니라
    "배분하는" 패턴이므로, 고른 전략을 **같은 Context에서 그대로 실행한다**.
    child로 띄우지 않는 이유: `spawn_agent`가 만드는 child는 `messages=[task]` 하나뿐이라
    대화 이력을 못 본다 — 라우터를 씌우는 순간 멀티턴이 깨진다 (ADR-0010).
    대신 어느 전략을 골랐는지는 `result.metadata['route']`와 로그에 남는다.

    확장 지점 셋:

    - `routes` — 아무 Strategy나 넣는다. 커스텀 전략도 `description` 한 줄만 있으면 낀다
      (없으면 클래스 이름을 대신 쓴다).
    - `context_route` — 거대 입력(`variables['context']`)이 오면 묻지 않고 갈 라우트 이름.
      기본은 `'rlm'`이고 `routes`에 그 키가 없으면 규칙이 발동하지 않는다. `None`이면 끈다.
    - `classify()` — 분류 로직 전체. 서브클래싱으로 규칙 기반·임베딩 기반으로 갈아끼우거나,
      분류만 싼 모델·낮은 temperature로 돌리는 것도 여기서 한다(코어는 그 손잡이를 따로 두지 않는다).

    비용은 `generate` 1회이고, 결정적 규칙에 걸리면 0회다.
    """

    description = 'Pick the strategy that fits the task, then let it solve the task.'
    prompt = ROUTER_PROMPT

    def __init__(
        self,
        routes: dict[str, Strategy],
        *,
        default: str,
        context_route: str | None = 'rlm',
        prompt: str | None = None,
        **limits: Any,
    ):
        super().__init__(**limits)
        if not routes:
            raise ValueError('routes must not be empty')
        if default not in routes:
            raise ValueError(f'default {default!r} is not one of routes {sorted(routes)}')
        self.routes = dict(routes)
        # 분류가 실패하면 전체가 실패하므로(어느 전략도 못 고른다) 선택이 아니라 필수 인자다.
        self.default = default
        self.context_route = context_route
        if prompt is not None:
            self.prompt = prompt

    def catalog(self) -> str:
        """모델에게 보여줄 전략 목록. description이 비면 클래스 이름으로 대신한다."""
        lines = [
            f'- {name}: {strategy.description or type(strategy).__name__}'
            for name, strategy in self.routes.items()
        ]
        return 'Available strategies:\n' + '\n'.join(lines)

    def rule(self, context: Context) -> str | None:
        """모델보다 먼저 보는 결정적 규칙. 없으면 None.

        거대 입력이 `variables['context']`로 들어왔다는 것은 "한 윈도우에 안 들어간다"는
        **사실**이지 판단이 아니다 — 모델에게 물으면 토큰만 쓰고 틀릴 기회만 준다.
        """
        if self.context_route in self.routes and context.variables.get('context') is not None:
            return self.context_route
        return None

    async def classify(self, context: Context, runtime: Runtime) -> str:
        """어느 라우트로 갈지 정한다. 서브클래스가 통째로 갈아끼우는 지점."""
        forced = self.rule(context)
        if forced is not None:
            return forced
        names = list(self.routes)
        response = await runtime.generate(
            context,
            tools=[RouteTool(names, self.prompt)],
            instructions=f'{self.prompt}\n\n{self.catalog()}',
        )
        if not response.tool_calls:
            # 모델이 형식을 못 지켰다(텍스트로 답함). Runtime.generate가 경고를 남긴다.
            return self.default
        chosen = response.tool_calls[0].arguments.get('strategy')
        return chosen if chosen in self.routes else self.default

    async def execute(self, context: Context, runtime: Runtime) -> AgentResult:
        name = await self.classify(context, runtime)
        logger.info(
            'run=%s exec=%s router.selected route=%s of %s',
            runtime.run_id, context.metadata.get('execution_id'), name, sorted(self.routes),
        )
        result = await self.routes[name].execute(context, runtime)
        # 트리에 별도 노드를 만들지 않으므로, "왜 이 전략인가"는 여기와 로그에만 남는다.
        result.metadata['route'] = name
        return result
