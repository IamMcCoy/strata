from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from strata.memory.base import Memory
from strata.memory.base import MemoryItem
from strata.memory.base import rank


class SQLiteMemory(Memory):
    """파일 하나로 영속 + 프로세스 간 공유. stdlib `sqlite3`라 런타임 의존성은 그대로 0개.

    프로세스가 죽어도 남고, 멀티 워커(같은 호스트)가 같은 파일을 공유한다 —
    InMemory가 못 하는 두 가지다. 워커가 여러 호스트에 흩어지면 RedisMemory로 간다.

    namespace가 곧 스코프다 — 사용자·세션별로 기억을 가르려면 인스턴스를 나눈다:
    `SQLiteMemory('mem.db', namespace=f'user:{uid}')`. retrieve에 필터 인자를 두지 않는 이유다.
    """

    # ponytail: sqlite3는 동기 API지만 로컬 파일이라 호출당 µs 단위 — 이벤트 루프를 의미 있게 막지 않는다.
    # 병목으로 측정되면 aiosqlite 또는 asyncio.to_thread로 감싼다.
    def __init__(self, path: str = 'strata_memory.db', namespace: str = 'default') -> None:
        self.namespace = namespace
        # check_same_thread=False: 이벤트 루프가 다른 스레드에서 돌 수 있다. WAL: 읽기와 쓰기가 서로 안 막는다.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS items ('
            'id TEXT PRIMARY KEY, ns TEXT NOT NULL, content TEXT NOT NULL, '
            'type TEXT NOT NULL, metadata TEXT NOT NULL)',
        )
        self.db.execute('CREATE INDEX IF NOT EXISTS items_ns ON items(ns)')
        self.db.commit()

    async def store(self, item: MemoryItem) -> None:
        item.id = item.id or uuid4().hex[:8]
        self.db.execute(
            'INSERT INTO items(id, ns, content, type, metadata) VALUES(?, ?, ?, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET content=excluded.content, type=excluded.type, metadata=excluded.metadata',
            (item.id, self.namespace, item.content, item.type, json.dumps(item.metadata)),
        )
        self.db.commit()

    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        # 점수는 SQL이 아니라 rank()가 매긴다 — FTS5의 unicode61 토크나이저는 '패키지를'과 '패키지'를
        # 다른 토큰으로 봐서 한국어에서 거의 다 빗나간다. 저장소가 달라도 관련성 판단은 하나여야 한다.
        rows = self.db.execute(
            'SELECT id, content, type, metadata FROM items WHERE ns = ?', (self.namespace,),
        ).fetchall()
        items = [MemoryItem(id=r[0], content=r[1], type=r[2], metadata=json.loads(r[3])) for r in rows]
        return rank(items, query, limit)

    async def delete(self, memory_id: str) -> None:
        self.db.execute('DELETE FROM items WHERE id = ? AND ns = ?', (memory_id, self.namespace))
        self.db.commit()

    def close(self) -> None:
        """연결을 닫는다. 파일을 여는 건 이 클래스이므로 닫는 것도 이 클래스의 몫이다."""
        self.db.close()

    def __enter__(self) -> SQLiteMemory:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
