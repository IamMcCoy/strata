from __future__ import annotations

from strata.agent.context import Context
from strata.runtime.runtime import Runtime
from strata.strategies.react import ReActStrategy
from strata.tools.python import PythonTool

RLM_INSTRUCTIONS = """\
You work in a Python REPL environment. Large inputs are NOT in this conversation — they are \
stored as Python variables that you can only inspect and process through the `python` tool. \
REPL state persists between calls.

Available variables:
{variables}

Helper: `llm_query(prompt: str, context=None) -> str` runs a fresh sub-agent with its own clean \
context window on `prompt`; if you pass `context` (e.g. a slice of a variable) the sub-agent sees it \
as its own `context` variable. Use it to divide and conquer large inputs (loop over chunks, collect \
answers in a variable) or to verify an answer against a small piece of evidence.

Work pattern: inspect (len, slices, regex) → chunk → delegate with llm_query → aggregate in \
variables → answer. When you have the final answer, reply with plain text and no tool call."""


def _describe_variables(variables: dict) -> str:
    """모델에게 보여줄 변수 목록(이름/타입/len). 내부 이름(_*)과 주입된 helper(callable)는 숨긴다."""
    lines = []
    for name, value in variables.items():
        if name.startswith('_') or callable(value):
            continue
        size = f', len={len(value)}' if hasattr(value, '__len__') else ''
        lines.append(f'- {name}: {type(value).__name__}{size}')
    return '\n'.join(lines) or '- (none yet)'


class RLMStrategy(ReActStrategy):
    """Recursive Language Model: ReAct loop + REPL(PythonTool) + llm_query 재귀 (ADR-0001/0007).

    문맥을 읽을 텍스트가 아니라 변수(Environment)로 다룬다 — `Agent.run(task, context=big)`이
    `variables['context']`에 넣고, 모델은 python tool로 조각내어 llm_query로 child에 넘긴다.
    child는 기본적으로 같은 전략을 상속해 다시 재귀할 수 있고 한도는 Runtime이 강제한다.
    registry에 'python' tool이 이미 있으면(샌드박스 구현 등) 그것을 쓴다(default_tools 규칙).
    """

    default_tools = (PythonTool(),)

    def instructions(self, context: Context, runtime: Runtime) -> str | None:
        env = RLM_INSTRUCTIONS.format(variables=_describe_variables(context.variables))
        return f'{context.instructions}\n\n{env}' if context.instructions else env
