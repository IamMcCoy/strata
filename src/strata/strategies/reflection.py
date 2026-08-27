from __future__ import annotations

from typing import Any

from strata.agent.context import Context
from strata.runtime.config import RuntimeConfig
from strata.runtime.runtime import Runtime
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy
from strata.strategies.react import ReActStrategy

# 비판자 child의 system 지시. 사용자 지시 뒤에 붙는다 — 사용자가 "한국어로" 같은 지시를 걸었으면
# 비판 라운드에서도 유지되어야 한다. 교체는 ReflectionStrategy(critic_prompt=...).
REFLECTION_CRITIC_PROMPT = """\
# You are a critic
You are reviewing a draft answer written by another agent. You are not the author and you do not rewrite it.

## What to produce
- An ordered list of concrete defects: factual errors, unsupported claims, requirements of the task the \
draft does not deliver, structural problems.
- For each defect say what is wrong and what would fix it. "Be clearer" is not a defect; "the second \
paragraph claims X without saying where X comes from" is.
- Judge the draft against the task it was given, not against the answer you would have written.

## What not to produce
- Do not rewrite the draft or supply the corrected version — a separate reviser does that.
- Do not pad the list with praise or style preferences.
- If the draft is already strong, still name its weakest points, ordered by how much they matter. \
An empty critique is not an outcome here."""

_CRITIQUE_TASK = """\
Critique the draft answer below.

## Original task
{task}

## Draft
{draft}"""

_REVISE_TASK = """\
Rewrite the draft answer below, applying the critique.
Reply with the revised answer only — no preamble, no notes about what you changed, no meta commentary.

## Original task
{task}

## Draft
{draft}

## Critique
{critique}"""


def _record(context: Context, draft: str | None) -> None:
    """현재 초안을 context의 마지막 assistant 메시지로 유지한다.

    두 가지를 산다: 취소·한도로 중간에 끊겨도 `last_assistant_text()`가 지금까지의 초안을
    살리고(ADR-0011/0013), 멀티턴 transcript에는 중간 초안이 쌓이지 않고 최신 답 하나만 남는다.
    """
    if context.messages and context.messages[-1].get('role') == 'assistant':
        context.messages[-1]['content'] = draft
    else:
        context.messages.append({'role': 'assistant', 'content': draft})


class ReflectionStrategy(Strategy):
    """Generate → Critique → Revise를 정해진 횟수만큼 도는 패턴.

    스스로 `generate`를 부르지 않는 첫 전략이다 — 초안·비판·수정을 전부 child로 띄우는
    오케스트레이터이고, 그래서 비판자의 문맥 격리가 공짜다(child는 parent 대화를 못 본다).

    `strategy=self.worker`는 선택이 아니라 필수다: 생략하면 child가 parent의 전략
    (=이 ReflectionStrategy)을 상속해 max_depth까지 재귀한다 (ADR-0006).

    조기 종료는 없다 — 비판자에게 "이제 충분한가"를 묻는 순간, 모델이 스스로 만족했는지
    판단하게 두지 않는다는 이 패턴의 존재 이유가 사라진다. 끄려면 rounds=0.
    이 노드는 generate를 부르지 않으므로 max_iterations가 걸리지 않는다 —
    실질 상한은 max_children(child 수 = 1 + rounds*2)이고, 초과분은 계약으로 돌아와 루프를 끝낸다.
    """

    def __init__(
        self,
        *,
        rounds: int = 2,
        worker: Strategy | None = None,
        critic_prompt: str = REFLECTION_CRITIC_PROMPT,
        **limits: Any,
    ):
        # 이 전략이 쓰는 child 수는 rounds에서 정해진다 — 사용자가 공식을 알아내 RuntimeConfig를
        # 고치게 하지 않고 전략이 제안한다. 명시적으로 준 max_children이 있으면 그것이 이긴다.
        #
        # 파생된 한도는 **하한**이지 상한이 아니다: 기본값보다 낮을 때 내리면 한도가 run 전체
        # 공유이므로 worker(예: RecursiveStrategy)가 재귀 위임에 쓸 자식 수까지 같이 조여진다.
        # 필요한 만큼만 올리고, 모자라지 않으면 아무것도 제안하지 않는다.
        needed = 1 + rounds * 2
        raise_to = {'max_children': needed} if needed > RuntimeConfig().max_children else {}
        super().__init__(**{**raise_to, **limits})
        self.rounds = rounds
        # 초안·수정을 맡는 child의 전략. 기본은 ReAct — tool을 쓰는 초안이 필요하면 tools만 주면 된다.
        self.worker = worker or ReActStrategy()
        self.critic_prompt = critic_prompt

    async def execute(self, context: Context, runtime: Runtime) -> AgentResult:
        task = context.metadata['task']
        draft = await runtime.spawn_agent(task, context, strategy=self.worker)
        if draft.status != 'completed':
            return draft  # 초안이 실패하면 고칠 것이 없다 — child의 계약을 그대로 올린다
        _record(context, draft.result)

        critic_instructions = '\n\n'.join(p for p in (context.instructions, self.critic_prompt) if p)
        rounds: list = []
        for _ in range(self.rounds):
            critique = await runtime.spawn_agent(
                _CRITIQUE_TASK.format(task=task, draft=draft.result),
                context, instructions=critic_instructions, strategy=self.worker,
            )
            if critique.status != 'completed':
                break  # 한도·실패로 끊기면 지금까지의 최선을 답으로 삼는다
            revised = await runtime.spawn_agent(
                _REVISE_TASK.format(task=task, draft=draft.result, critique=critique.result),
                context, strategy=self.worker,
            )
            if revised.status != 'completed':
                break
            rounds.append({'critique': critique.result, 'draft': revised.result})
            draft = revised
            _record(context, draft.result)

        return AgentResult(
            result=draft.result,
            evidence=rounds,
            metadata={'rounds_completed': len(rounds)},
        )
