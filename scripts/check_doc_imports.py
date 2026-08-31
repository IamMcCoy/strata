"""문서에 적힌 import가 실제로 되는지 검사한다.

`from strata import X`를 `from strata.strategies import X`로 옮기는 식의 일괄 수정에서
이름을 엉뚱한 서브패키지에 붙여도 마크다운은 아무 말이 없다. 실행해서 확인한다.

실행: uv run python scripts/check_doc_imports.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

CODE_BLOCK = re.compile(r'^```python\n(.*?)^```', re.M | re.S)
IMPORT_LINE = re.compile(r'^(?:from strata[\w.]* import .+|import strata[\w.]*)$', re.M)


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in sorted(ROOT.rglob('*.md')):
        if any(part in {'.git', 'dist', '.venv', 'api'} for part in path.parts):
            continue
        for block in CODE_BLOCK.findall(path.read_text()):
            for line in IMPORT_LINE.findall(block):
                checked += 1
                try:
                    exec(line, {})
                except Exception as exc:
                    failures.append(f'{path.relative_to(ROOT)}: {line}\n    → {exc!r}')

    for f in failures:
        print(f'실패 {f}')
    print(f'\n{checked}개 import 검사, 실패 {len(failures)}개')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
