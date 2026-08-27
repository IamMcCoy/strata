"""전체 파이프라인 통합 테스트 — 실제 Redis + 실제 워커 프로세스. 실행: `make test-integration`.

examples/worker.py를 그대로 실행해서 검증한다. 예제가 곧 테스트 대상이므로 예제가 썩지 않는다
(CLAUDE.md: 검증은 저장소 안의 실행 가능한 파일로).

OPENAI_API_KEY를 지우고 돌린다 — ScriptedProvider 경로를 타므로 CI에서 비용도 네트워크도 없다.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from strata import Agent
from strata import InMemory
from strata import MemoryTool
from strata import ReActStrategy

sys.path.insert(0, str(Path(__file__).parent.parent / 'tests'))
from conftest import call      # noqa: E402
from conftest import final     # noqa: E402
from conftest import ScriptedProvider  # noqa: E402

REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
ROOT = Path(__file__).parent.parent


pytestmark = pytest.mark.integration


def _redis_is_up() -> bool:
    try:
        socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=0.5).close()
        return True
    except OSError:
        return False


needs_redis = pytest.mark.skipif(
    not _redis_is_up(), reason=f'Redis({REDIS_HOST}:{REDIS_PORT}) 미기동 — `make redis-up`',
)


@needs_redis
def test_worker_example_runs_the_whole_pipeline():
    """task_id 발급 → 큐 → 별개 프로세스 워커 → Tool 실행 → Memory 공유 → 결과 조회."""
    env = {**os.environ, 'REDIS_PORT': str(REDIS_PORT)}
    env.pop('OPENAI_API_KEY', None)  # ScriptedProvider 경로 — 비용·네트워크 없음

    done = subprocess.run(
        [sys.executable, 'examples/worker.py'],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    assert done.returncode == 0, f'stdout:\n{done.stdout}\nstderr:\n{done.stderr}'

    out = done.stdout
    assert '[tool] add(12, 30)' in out, 'Tool이 실제로 실행돼야 한다'
    assert 'history로 답함' in out, '큐로 실어보낸 history가 다음 턴에 쓰여야 한다'
    assert 'Memory가 워커 경계를 넘었다' in out, 'history 없이 다른 워커가 기억을 읽어야 한다'
    assert '파이프라인 OK' in out
    assert out.count(' run=01') == 4, f'결과마다 코어가 발급한 run_id가 붙어야 한다:\n{out}'
    assert out.count('처리 시작') == 4, f'작업 4개가 모두 처리돼야 한다:\n{out}'


def test_queue_payload_is_pure_json():
    """큐에 실리는 건 데이터뿐 — Agent는 워커가 소유한다 (그래서 코어에 큐를 두지 않는다).

    ToolCall 객체가 messages에 섞이면 여기서 TypeError로 잡힌다.
    """
    provider = ScriptedProvider([call('remember', content='사실'), final('저장했습니다')])
    result = asyncio.run(
        Agent(
            provider=provider, strategy=ReActStrategy(), tools=[MemoryTool()], memory=InMemory(),
        ).run('기억해'),
    )

    job = {'id': 'abc123', 'task': '다음 질문', 'history': result.metadata['messages']}
    restored = json.loads(json.dumps(job))  # 큐를 왕복하는 지점
    assert restored == job
    assert any(m.get('tool_calls') for m in restored['history'])


if __name__ == '__main__':
    test_worker_example_runs_the_whole_pipeline()
    test_queue_payload_is_pure_json()
    print('pipeline ok')
