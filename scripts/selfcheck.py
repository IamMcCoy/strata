#!/usr/bin/env python3
"""strata 자기검사 — 이 저장소의 코드를 strata에 먹여 불변식 위반을 찾는다.

실행:
    OPENAI_BASE_URL=http://192.168.1.70:32757/v1 OPENAI_MODEL=Gemma4-12B-it \
        uv run python scripts/selfcheck.py [--verbose]

`tests/`도 `examples/`도 아닌 이유: 실제 모델을 부르고 결과가 매번 다르다(테스트에 못 넣는다).
키·엔드포인트가 필요하다(예제에 못 넣는다). 사람이 필요할 때 돌리는 도구다.

동시에 dogfooding이다 — 소비자가 하는 조립을 그대로 한다:

    Provider + Tool + Strategy + instructions → Agent → 파일마다 run()

**순회는 파이썬이, 판단만 모델이 한다.** 파일 목록은 이미 아는 결정적 정보라 모델에게
for문을 대신 쓰게 할 이유가 없다(RLM은 *자르는 법을 모를 때* 쓴다). 실측으로도 12B 모델은
바깥 루프까지 맡기면 무너졌다 — 가짜 tool call을 텍스트로 뱉고 파일 내용을 지어냈다.

불변식은 하드코딩하지 않고 `CLAUDE.md`에서 읽어 `instructions`로 넣는다(매 run의 system).
문서가 바뀌면 검사도 바뀐다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from strata import Agent                # noqa: E402
from strata import OpenAIProvider       # noqa: E402
from strata import ReActStrategy        # noqa: E402
from strata import RuntimeConfig        # noqa: E402
from strata import Tool                 # noqa: E402
from strata import ToolEnv              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def invariants() -> str:
    """CLAUDE.md의 '아키텍처' 절 원문. 문서가 검사의 단일 출처다."""
    text = (ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
    start = text.index('## 아키텍처')
    end = text.index('\n## ', start + 1)
    return text[start:end].strip()


def sources() -> dict[str, str]:
    """검사 대상 = 패키지 소스 전체. messages가 아니라 variables로 들어간다."""
    return {
        str(path.relative_to(ROOT)): path.read_text(encoding='utf-8')
        for path in sorted((ROOT / 'src').rglob('*.py'))
        if path.stat().st_size > 0
    }


class ReportViolationTool(Tool):
    """발견을 산문에서 파싱하지 않고 구조화해 받는다 — Tool이 결과 수집 지점이다.

    child agent도 registry의 tool을 그대로 보므로(Strategy.tools), 조각을 맡은 child가
    직접 호출할 수 있다. 수집은 이 인스턴스에 쌓인다.
    """

    name = 'report_violation'
    description = (
        'Record one concrete violation of a stated invariant. Call once per violation. '
        'Only report what you can point at in the given source — never guess.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'file': {'type': 'string', 'description': 'Path of the offending file'},
            'invariant': {'type': 'string', 'description': 'Which invariant is broken (short quote or number)'},
            'evidence': {'type': 'string', 'description': 'The exact line(s) of code that break it'},
            'detail': {'type': 'string', 'description': 'Why this breaks the invariant'},
        },
        'required': ['file', 'invariant', 'evidence', 'detail'],
    }

    def __init__(self) -> None:
        self.found: list[dict[str, str]] = []

    async def execute(self, env: ToolEnv, **kwargs: Any) -> Any:
        self.found.append({key: kwargs.get(key, '') for key in self.input_schema['properties']})
        return f'recorded ({len(self.found)} so far)'


AUDIT_INSTRUCTIONS = """\
You audit source files of this framework against its architectural invariants.

{invariants}

# How to answer
- Report a violation only when you can quote the exact line in the file you were given.
- Use the `report_violation` tool, once per violation. Then reply in plain text.
- A file that follows the rules is the normal case. If you find nothing, reply exactly: OK
- Never report style, naming, or design opinions — only the numbered invariants above.
- Never guess about code you were not shown. Other files are out of scope."""

FILE_TASK = """\
Audit {path} against the invariants.

# Source
```python
{source}
```"""


# 불변식 2를 명백히 어기는 합성 파일. 이걸 못 잡으면 "위반 없음"은 아무 의미가 없다.
PLANTED_PATH = 'src/strata/strategies/planted.py'
PLANTED_SOURCE = '''from __future__ import annotations

from strata.providers.openai import OpenAIProvider
from strata.strategies.base import AgentResult
from strata.strategies.base import Strategy


class LeakyStrategy(Strategy):
    """Provider를 직접 부르는 전략."""

    async def execute(self, context, runtime) -> AgentResult:
        # runtime.generate를 거치지 않고 provider를 직접 호출한다
        response = await runtime.provider.generate(context.messages)
        fallback = OpenAIProvider(model='gpt-4o-mini')
        return AgentResult(result=response.text)
'''


async def audit_file(agent: Agent, path: str, source: str) -> tuple[str, int, int]:
    """파일 하나를 감사한다. run마다 Runtime이 새로 생긴다 (ADR-0006)."""
    result = await agent.run(FILE_TASK.format(path=path, source=source))
    return result.status, agent.runtime.usage['total_tokens'], len(result.result or '')


async def main() -> int:
    verbose = '--verbose' in sys.argv
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(message)s',
    )
    logging.getLogger('strata').setLevel(logging.DEBUG if verbose else logging.INFO)

    base_url = os.environ.get('OPENAI_BASE_URL')
    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
    if not (base_url or os.environ.get('OPENAI_API_KEY')):
        print('OPENAI_BASE_URL 또는 OPENAI_API_KEY가 필요하다. 예:')
        print(
            '  OPENAI_BASE_URL=http://host:port/v1 OPENAI_MODEL=<model> '
            'uv run python scripts/selfcheck.py',
        )
        return 2
    # 파일 하나당 child 하나를 띄우므로 실수로 유료 엔드포인트에 나가면 비싸다.
    # base_url이 없으면 상용 OpenAI다 — 명시적으로 --yes를 받는다.
    print(f'endpoint: {base_url or "https://api.openai.com/v1 (유료)"}  model: {model}')
    if not base_url and '--yes' not in sys.argv:
        print(
            '상용 OpenAI로 나간다. 의도한 것이면 --yes 를 붙여라 '
            '(로컬 엔드포인트는 OPENAI_BASE_URL 지정).',
        )
        return 2

    code = {PLANTED_PATH: PLANTED_SOURCE} if '--planted' in sys.argv else sources()
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
        code = dict(list(code.items())[:limit])
    print(f'검사 대상: {len(code)}개 파일, {sum(len(v) for v in code.values()):,} chars\n')

    reporter = ReportViolationTool()
    agent = Agent(
        provider=OpenAIProvider(
            model=model,
            api_key=os.environ.get('OPENAI_API_KEY') or 'not-needed',
            base_url=base_url,
            max_retries=3,
        ),
        strategy=ReActStrategy(),
        tools=[reporter],
        instructions=AUDIT_INSTRUCTIONS.format(invariants=invariants()),
        # 파일 하나에 tool 호출 몇 번이면 끝난다 — 루프가 도는 건 이상 신호다.
        config=RuntimeConfig(max_iterations=8, timeout=180),
    )

    failures, tokens = [], 0
    for index, (path, source) in enumerate(code.items(), start=1):
        before = len(reporter.found)
        try:
            status, used, _ = await audit_file(agent, path, source)
        except Exception as exc:  # 한 파일이 죽어도 감사 전체를 멈추지 않는다
            failures.append((path, repr(exc)))
            print(f'  [{index:2}/{len(code)}] {path:42} ✗ {type(exc).__name__}')
            continue
        tokens += used
        found = len(reporter.found) - before
        mark = '✗' if status != 'completed' else ('!' if found else '·')
        print(
            f'  [{index:2}/{len(code)}] {path:42} {mark} {status}'
            + (f'  위반 {found}건' if found else ''),
        )
        if status != 'completed':
            failures.append((path, status))

    print('\n' + '=' * 70)
    if reporter.found:
        print(f'--- 발견 {len(reporter.found)}건 ---')
        print(json.dumps(reporter.found, ensure_ascii=False, indent=2))
    else:
        print('--- 위반 없음 ---')
    if failures:
        print(f'\n--- 감사하지 못한 파일 {len(failures)}개 ---')
        for path, why in failures:
            print(f'  {path}: {why}')
    print(f'\n총 {tokens:,} tokens')
    if '--planted' in sys.argv:
        ok = bool(reporter.found)
        print('심어둔 위반을 ' + ('잡았다 — 감사기에 신호가 있다.' if ok else '놓쳤다 — 이 모델로는 감사 결과를 믿을 수 없다.'))
        return 0 if ok else 1
    # 발견은 모델의 주장이므로 종료 코드로 실패를 만들지 않는다. 실행 자체가 실패한 경우만 1.
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
