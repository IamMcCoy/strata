from __future__ import annotations

from strata.agent.context import Context
from strata.strategies.react import REACT_PROMPT
from strata.strategies.react import ReActStrategy
from strata.tools.python import PythonTool

RLM_PROMPT = REACT_PROMPT + """

# Working in the Python REPL
Large inputs are NOT in this conversation. They are stored as Python variables that you can only \
inspect and process through the `python` tool. The REPL is persistent: variables, imports, and \
functions you define survive between calls. Never reassign `context` itself — derive new variables from it. \
The end of this message lists the variables that exist right now (refreshed every turn) and the \
helpers that are always injected — `llm_query` is one of them, so it is available even though it \
is not a variable.

## Inspecting without flooding the window
- Start by measuring whatever is listed below (if `context` is there: `len(context)`, `type(context)`, \
`context[:500]`). If no large variable is listed, there is no hidden input — answer from the task itself. \
Never print a large variable whole — output is truncated and you learn nothing. Use slices, `re` searches, \
counts, and summaries.
- Each REPL call returns the printed output plus the value of a trailing expression; a Python \
traceback is an observation, not a failure of the task — fix the code and run it again.

## Delegating with llm_query
- `llm_query(prompt: str, context=None) -> str` runs a fresh sub-agent with its own clean window. \
It sees only `prompt` and, if given, `context` as its own `context` variable — never this conversation \
or your variables. Make `prompt` self-contained and tell it exactly what to return (format, length, \
"answer NONE if absent").
- Use it for divide and conquer: split the input into chunks sized for one window (a few thousand \
characters or logical units such as chapters/records), loop `llm_query` over them, and collect the \
answers in a variable. One `python` call may issue many `llm_query` calls.
- Use it to verify: re-ask a narrow question against the small piece of evidence that should contain the answer.
- If a result starts with `[failed]` or `[budget_exceeded]`, do not loop on it blindly: shrink the chunk, \
rephrase, or handle that piece directly. Limits on depth and children apply to every agent.

## Work pattern
inspect (len, slices, regex) → chunk → delegate with llm_query → aggregate in variables → verify → answer \
(plain text, no tool call — see Finishing above)."""


def _describe_variables(variables: dict) -> str:
    """모델에게 보여줄 변수 목록(이름/타입/len). 내부 이름(_*)과 주입된 helper(callable)는 숨긴다."""
    lines = []
    for name, value in variables.items():
        if name.startswith('_') or callable(value):
            continue
        try:
            size = f', len={len(value)}'
        except Exception:  # 모델이 만든 객체의 __len__이 없거나 터져도 하네스는 죽지 않는다 — 크기만 생략
            size = ''
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
    prompt = RLM_PROMPT

    def environment(self, context: Context) -> str:
        """현재 변수 목록 + 항상 주입되는 helper — 모델이 REPL에서 만든 변수는 다음 호출의 system에 나타난다.

        helper를 따로 적는 이유: 변수 목록은 callable을 숨기므로 `llm_query`가 거기 절대 안 나타난다.
        그런데 프롬프트는 이 목록을 권위 있는 것으로 말한다 — 약한 모델은 목록을 믿고
        "llm_query는 없다"고 결론내고 재귀를 포기한다(실측: Gemma4-12B). 두 출처의 모순을 없앤다.
        """
        return (
            '## Current variables\n' + _describe_variables(context.variables)
            + '\n\n## Always injected into the REPL (not variables)\n'
            + '- llm_query(prompt: str, context=None) -> str'
        )
