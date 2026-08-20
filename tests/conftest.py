"""pytest 공통 설정: 저장소 루트의 .env를 환경변수로 로드한다.

터미널이든 IDE(인텔리제이)든 pytest 실행 경로와 무관하게 API 키가 잡히게 한다.
.env는 gitignore되어 있다 — .env.example을 복사해서 만든다.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')
