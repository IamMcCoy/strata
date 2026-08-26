"""패키징 계약 — 코드가 안내하는 extra는 실제로 존재해야 한다.

존재하지 않는 extra는 설치 시 **에러 없이 조용히 무시된다.** 사용자는 설치했다고 믿고
다시 실행해 같은 ImportError를 만난다 — 무한루프다. 그래서 코드 문자열과 pyproject를
자동으로 대조한다.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
ADVERTISED = re.compile(r'strata\[([a-z0-9_-]+)\]')
# 'all'은 다른 extra들을 묶기만 하는 집계용이라 특정 코드 경로가 안내하지 않는다.
AGGREGATE = {'all'}


def defined_extras() -> set[str]:
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    return set(data['project'].get('optional-dependencies', {}))


def advertised_extras() -> dict[str, list[str]]:
    """소스가 안내하는 extra → 그걸 언급한 파일들."""
    found: dict[str, list[str]] = {}
    for path in (ROOT / 'src').rglob('*.py'):
        for name in ADVERTISED.findall(path.read_text()):
            found.setdefault(name, []).append(str(path.relative_to(ROOT)))
    return found


def test_every_advertised_extra_exists():
    advertised = advertised_extras()
    assert advertised, '안내문을 하나도 못 찾았다 — 정규식이 깨졌는지 확인하라'
    missing = {name: files for name, files in advertised.items() if name not in defined_extras()}
    assert not missing, f'pyproject에 없는 extra를 안내하고 있다: {missing}'


def test_core_has_no_runtime_dependencies():
    """의존성 0개가 이 프로젝트의 정체성이다 — extra로 새어 들어가면 안 된다."""
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    assert data['project']['dependencies'] == []


def test_every_extra_is_advertised_somewhere():
    """반대 방향 — 아무 코드도 안내하지 않는 extra는 사용자가 존재를 알 수 없다."""
    orphans = defined_extras() - set(advertised_extras()) - AGGREGATE
    assert not orphans, f'코드가 안내하지 않는 extra: {orphans}'


def test_the_all_extra_covers_every_other_extra():
    """'strata[all]'이 하나라도 빠뜨리면 '다 깔았는데 안 되는' 상황이 된다."""
    import tomllib
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    extras = data['project']['optional-dependencies']
    bundled = set(re.findall(r'strata\[([^\]]+)\]', ' '.join(extras['all']))[0].split(','))
    assert bundled == set(extras) - AGGREGATE, f"all이 덮지 못하는 extra가 있다: {set(extras) - AGGREGATE - bundled}"


if __name__ == '__main__':
    test_every_advertised_extra_exists()
    test_core_has_no_runtime_dependencies()
    test_every_extra_is_advertised_somewhere()
    test_the_all_extra_covers_every_other_extra()
    print('packaging ok')
