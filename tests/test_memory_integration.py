"""실제 Redis + 실제 SQLite 파일 + 실제 멀티프로세스 검증. 실행: `make test-integration`.

단위 테스트(tests/test_memory.py)는 fake로 계약을 본다. 여기서는 그 계약이 진짜 인프라에서도
성립하는지만 본다 — 특히 "워커가 2개 이상이면 기억이 공유되는가"를 실제 프로세스로 증명한다.

Redis가 떠 있지 않으면 모듈 전체를 skip한다: docker 없이도 `uv run pytest`는 초록이어야 한다.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import multiprocessing as mp
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import call
from conftest import final
from conftest import ScriptedProvider
from strata.agent import Agent
from strata.memory import InMemory
from strata.memory import MemoryItem
from strata.memory import RedisMemory
from strata.memory import SQLiteMemory
from strata.strategies import ReActStrategy
from strata.tools import MemoryTool

FACT = '사용자는 패키지 관리에 uv를 쓴다'
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - dev 의존성 미설치
    redis_asyncio = None


pytestmark = pytest.mark.integration


def _redis_is_up() -> bool:
    if redis_asyncio is None:
        return False
    try:
        socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=0.5).close()
        return True
    except OSError:
        return False


# Redis 테스트에만 건다 — 아래 멀티프로세스 검증은 docker 없이도 돌아야 한다.
needs_redis = pytest.mark.skipif(
    not _redis_is_up(), reason=f'Redis({REDIS_HOST}:{REDIS_PORT}) 미기동 — `make redis-up`',
)


def asyncio_test(fn):
    """테스트 본문 전체를 이벤트 루프 하나에서 돌린다.

    redis.asyncio 연결은 자기를 만든 루프에 묶인다 — 호출마다 asyncio.run()을 쓰면
    두 번째 호출에서 'Event loop is closed'로 죽는다. 실제 클라이언트에서만 드러나는 제약이다.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@contextlib.asynccontextmanager
async def redis_client():
    """테스트마다 새 연결, 끝나면 flushdb — 실제 서버는 상태가 남는다."""
    conn = redis_asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)
    try:
        yield conn
    finally:
        await conn.flushdb()
        await conn.aclose()


# --- 실제 Redis ------------------------------------------------------------

@needs_redis
@asyncio_test
async def test_real_redis_roundtrip():
    """단위 테스트의 FakeRedis가 아니라 진짜 서버 — bytes 응답 경로가 실제로 도는지."""
    async with redis_client() as client:
        memory = RedisMemory(client, namespace='it:roundtrip')
        for content in ('커피를 좋아한다', 'uv로 패키지를 설치한다'):
            await memory.store(MemoryItem(content=content))

        hits = await memory.retrieve('uv 패키지')
        assert [h.content for h in hits] == ['uv로 패키지를 설치한다']
        assert hits[0].id, 'id가 되살아나야 delete를 할 수 있다'

        await memory.delete(hits[0].id)
        assert await memory.retrieve('uv 패키지') == []


@needs_redis
@asyncio_test
async def test_real_redis_shares_between_independent_clients():
    """워커 A(클라이언트 1)가 저장한 걸 워커 B(클라이언트 2)가 읽는다 — 멀티 워커의 핵심."""
    async with redis_client() as worker_a:
        worker_b = redis_asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT)  # 별개 프로세스의 별개 연결
        try:
            await RedisMemory(worker_a, namespace='it:share').store(MemoryItem(content=FACT))
            hits = await RedisMemory(worker_b, namespace='it:share').retrieve('uv')
            assert [h.content for h in hits] == [FACT]
        finally:
            await worker_b.aclose()


@needs_redis
@asyncio_test
async def test_real_redis_namespace_isolation():
    async with redis_client() as client:
        await RedisMemory(client, namespace='it:user:alice').store(MemoryItem(content=FACT))
        assert await RedisMemory(client, namespace='it:user:bob').retrieve('uv') == []


@needs_redis
@asyncio_test
async def test_agent_lifecycle_on_real_redis():
    """retrieve(자동) → Context.instructions, store(명시적) → MemoryTool 이 실제 서버에서도 돈다."""
    async with redis_client() as client:
        memory = RedisMemory(client, namespace='it:agent')

        def agent(provider):
            return Agent(provider=provider, strategy=ReActStrategy(), tools=[MemoryTool()], memory=memory)

        writer = ScriptedProvider([call('remember', content=FACT), final('기억해뒀습니다')])
        assert (await agent(writer).run('앞으로 uv를 쓴다는 걸 기억해')).status == 'completed'

        reader = ScriptedProvider([final('uv로 설치하세요')])
        await agent(reader).run('패키지 설치는 어떻게 해?')
        system = reader.seen[0][0]
        assert system['role'] == 'system' and FACT in system['content']


@needs_redis
@asyncio_test
async def test_from_url_builds_a_working_client():
    """주소만 넘기는 지름길 — 지연 import라 런타임 의존성은 그대로 0개다."""
    memory = RedisMemory.from_url(f'redis://{REDIS_HOST}:{REDIS_PORT}', namespace='it:url')
    try:
        await memory.store(MemoryItem(content=FACT))
        assert [h.content for h in await memory.retrieve('uv')] == [FACT]
    finally:
        await memory.client.flushdb()
        await memory.client.aclose()


def test_importing_strata_does_not_import_redis():
    """의존성 0개의 실제 의미 — strata를 import해도 redis는 로드되지 않는다."""
    code = 'import sys, strata; assert "redis" not in sys.modules, sys.modules.keys()'
    assert subprocess.run([sys.executable, '-c', code], capture_output=True).returncode == 0


# --- 실제 멀티프로세스 (원래 질문: "워커가 1개 이상이라면?") ----------------------

def _store_in_child(path: str, content: str) -> None:
    """자식 프로세스에서 실행된다. macOS는 spawn이라 부모 메모리를 전혀 물려받지 않는다."""
    memory = SQLiteMemory(path, namespace='worker')
    asyncio.run(memory.store(MemoryItem(content=content)))
    memory.close()


def test_sqlite_is_shared_across_real_processes(tmp_path: Path):
    """워커 A(자식 프로세스)가 저장 → 워커 B(부모)가 읽는다. SQLiteMemory가 멀티워커를 견딘다는 증명."""
    path = str(tmp_path / 'workers.db')
    SQLiteMemory(path, namespace='worker').close()  # 스키마 준비

    child = mp.get_context('spawn').Process(target=_store_in_child, args=(path, FACT))
    child.start()
    child.join(timeout=30)
    assert child.exitcode == 0, '자식 프로세스가 실패했다'

    parent = SQLiteMemory(path, namespace='worker')
    assert [h.content for h in asyncio.run(parent.retrieve('uv'))] == [FACT]
    parent.close()


def test_sqlite_concurrent_writers_do_not_block_each_other(tmp_path: Path):
    """WAL 확인 — 두 프로세스가 동시에 써도 database is locked로 죽지 않는다."""
    path = str(tmp_path / 'concurrent.db')
    SQLiteMemory(path, namespace='worker').close()

    ctx = mp.get_context('spawn')
    children = [ctx.Process(target=_store_in_child, args=(path, f'사실 {i}번')) for i in range(4)]
    for child in children:
        child.start()
    for child in children:
        child.join(timeout=30)
    assert [c.exitcode for c in children] == [0, 0, 0, 0]

    memory = SQLiteMemory(path, namespace='worker')
    assert len(asyncio.run(memory.retrieve('사실'))) == 4
    memory.close()


def test_inmemory_does_not_survive_a_process_boundary():
    """대조군 — InMemory는 프로세스를 못 넘는다. SQLite/Redis가 필요한 이유 그 자체."""
    memory = InMemory()
    asyncio.run(memory.store(MemoryItem(content=FACT)))
    assert len(memory.items) == 1

    # 자식 프로세스는 이 dict를 못 본다. 자식이 저장해도 부모에 안 보인다 —
    # 그래서 멀티 워커 배포에서는 기억이 워커마다 갈라진다.
    assert asyncio.run(InMemory().retrieve('uv')) == []
