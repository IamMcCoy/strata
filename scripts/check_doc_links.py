#!/usr/bin/env python3
"""저장소의 모든 마크다운 상대 링크가 실제 파일을 가리키는지 검사한다.

사용: uv run python scripts/check_doc_links.py
깨진 링크가 있으면 목록을 출력하고 exit 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {'.git', '.venv', 'dist', 'node_modules', '__pycache__'}
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')

broken: list[str] = []
for md in sorted(ROOT.rglob('*.md')):
    if SKIP_DIRS & set(md.relative_to(ROOT).parts):
        continue
    for target in LINK.findall(md.read_text(encoding='utf-8')):
        if target.startswith(('http://', 'https://', 'mailto:', '#')):
            continue
        path = target.split('#', 1)[0]
        if path and not (md.parent / path).exists():
            broken.append(f'{md.relative_to(ROOT)}: {target}')

if broken:
    print('깨진 링크:')
    print('\n'.join(f'  {b}' for b in broken))
    sys.exit(1)
print(f'OK — 깨진 상대 링크 없음 ({ROOT} 아래 *.md 전체)')
