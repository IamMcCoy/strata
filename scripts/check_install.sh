#!/usr/bin/env bash
# 소비자 설치 검증: wheel 빌드 → 깨끗한 venv에 설치 → 실사용 코드 실행
# 실행: scripts/check_install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf dist
uv build

VENV="$(mktemp -d)/venv"
uv venv -q "$VENV"
uv pip install -q --python "$VENV/bin/python" dist/strata-*.whl

# 개발 환경이 아닌, 설치된 wheel만으로 예제가 end-to-end 동작하는지
"$VENV/bin/python" examples/react.py

# 타입 힌트 마커(PEP 561)가 wheel에 포함됐는지
"$VENV/bin/python" -c "
import pathlib, strata
assert (pathlib.Path(strata.__file__).parent / 'py.typed').exists(), 'py.typed missing in wheel'
print('py.typed OK')
"

echo 'consumer install OK'
