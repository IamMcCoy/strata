from __future__ import annotations

import ast
import asyncio
import functools
import io
import traceback
from typing import Any

from strata.tools.base import Tool
from strata.tools.base import ToolEnv


class PythonTool(Tool):
    """RLM의 Environment — 프로세스 내 Python REPL.

    - 네임스페이스는 호출한 agent의 `context.variables` 그 자체 → 호출 간 상태가 유지되고,
      `variables['context']`에 담긴 거대 입력을 모델이 코드로만 다룬다.
    - `llm_query(prompt, context=None)` 가 주입된다 → env.runtime.spawn_agent. 코드 안에서
      동기 함수처럼 호출되지만 실제로는 이벤트 루프의 child agent 실행을 기다린다
      (exec는 worker thread에서 돌고 run_coroutine_threadsafe로 루프에 넘긴다).
    - **샌드박스 없음.** 모델이 만든 코드가 이 프로세스 권한으로 실행된다 — 신뢰된 환경 전용.
      격리가 필요하면 같은 name/schema로 Docker·원격 커널 기반 Tool을 구현해 registry에 등록한다.
    """

    name = 'python'
    description = (
        'Execute Python code in a persistent REPL (Jupyter-like: variables persist between calls, '
        'and the value of a trailing expression is shown; use print() for anything else). '
        'Large inputs are available as variables (see system instructions); call '
        'llm_query(prompt, context=...) to delegate a piece of work to a fresh sub-agent and get '
        'its answer as a string.'
    )
    input_schema = {
        'type': 'object',
        'properties': {'code': {'type': 'string', 'description': 'Python code to execute'}},
        'required': ['code'],
    }
    # ponytail: 관찰 크기 상한 — 모델이 거대 변수를 통째로 print해도 window가 터지지 않게
    max_output = 10_000

    async def execute(self, env: ToolEnv, code: str = '', **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        namespace = env.context.variables
        out = io.StringIO()

        def llm_query(prompt: str, context: Any = None) -> str:
            future = asyncio.run_coroutine_threadsafe(
                env.runtime.spawn_agent(prompt, env.context, context=context), loop,
            )
            result = future.result()
            if result.status == 'completed':
                return result.result or ''
            return f'[{result.status}] {result.result or result.metadata}'

        namespace['llm_query'] = llm_query
        namespace['print'] = functools.partial(print, file=out)  # 스레드 안전한 stdout 캡처

        def run() -> str:
            try:
                _exec_repl(code, namespace, out)
            except Exception as exc:
                out.write(_format_error(exc))
            return out.getvalue()

        output = await asyncio.to_thread(run)
        if len(output) > self.max_output:
            output = output[: self.max_output] + f'\n... [truncated, {len(output)} chars total]'
        return output or '(no output)'


def _exec_repl(code: str, namespace: dict, out: io.StringIO) -> None:
    """Jupyter 의미론: 마지막 문장이 표현식이면 그 값(repr)을 출력한다 — 모델이 기대하는 REPL 동작."""
    tree = ast.parse(code, filename='<python>', mode='exec')
    last = tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    if last is not None:
        tree.body.pop()
    exec(compile(tree, '<python>', 'exec'), namespace)
    if last is not None:
        value = eval(compile(ast.Expression(last.value), '<python>', 'eval'), namespace)
        if value is not None:
            out.write(repr(value) + '\n')


def _format_error(exc: BaseException) -> str:
    """모델 코드 프레임(<python>)만 남긴 traceback — 프레임워크 내부 경로는 노이즈다."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == '<python>']
    lines = ['Traceback (most recent call last):\n', *traceback.format_list(frames)] if frames else []
    return ''.join(lines + traceback.format_exception_only(exc))
