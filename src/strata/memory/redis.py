from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from strata.memory.base import Memory
from strata.memory.base import MemoryItem
from strata.memory.base import rank


class RedisMemory(Memory):
    """여러 호스트의 워커가 기억을 공유해야 할 때. 클라이언트를 주입받는다.

    strata는 redis를 import하지 않는다 — 런타임 의존성 0개가 유지되고, 연결 풀·재연결·타임아웃
    정책은 코어가 아니라 애플리케이션의 몫으로 남는다. 사용자가 자기 클라이언트를 넘긴다:

        import redis.asyncio as redis
        memory = RedisMemory(redis.Redis(host='...'), namespace=f'user:{uid}')

    client는 `hset` / `hgetall` / `hdel`을 await할 수 있으면 무엇이든 된다.
    namespace가 곧 스코프다 — 사용자·세션별로 가르려면 **클라이언트는 공유하고 인스턴스만** 나눈다.
    그래야 커넥션 풀 하나를 N명이 함께 쓴다.

    주소만 있고 클라이언트가 없다면 `RedisMemory.from_url('redis://...')`.

    주의: redis.asyncio 클라이언트는 자기를 만든 이벤트 루프에 묶인다. 루프가 닫히면 그 연결도
    끝난다("Event loop is closed") — 프로세스/루프당 하나를 만들어 재사용한다.
    """

    # ponytail: hgetall로 전부 가져와 rank()로 점수를 매긴다. namespace당 항목이 수천을 넘으면
    # RediSearch 인덱스나 VectorMemory로 간다 — 그 전까지는 왕복 1회가 가장 싸고 단순하다.
    def __init__(self, client: Any, namespace: str = 'strata') -> None:
        self.client = client
        self.namespace = namespace

    @classmethod
    def from_url(cls, url: str, namespace: str = 'strata', **kwargs: Any) -> RedisMemory:
        """주소만으로 만드는 지름길. `redis`는 이 메서드 안에서만 import한다 — 의존성 0개는 그대로다.

        비동기 클라이언트를 강제하는 역할도 한다: 동기 `redis.Redis`를 주입하면
        await 시점에 해독하기 어려운 TypeError가 나기 때문이다.

        커넥션 풀을 하나 새로 만든다 — namespace를 여러 개 쓸 때는 이걸 반복 호출하지 말고
        클라이언트 하나를 만들어 `RedisMemory(client, namespace=...)`로 나눈다.
        """
        try:
            # 지연 import: 이 경로를 쓰는 사용자만 redis가 필요하다.
            # 클라이언트를 주입받는 기본 경로는 redis 없이도 동작한다.
            import redis.asyncio as redis
        except ImportError as exc:
            raise ImportError(
                "RedisMemory.from_url requires the redis package: uv add 'strata[redis]'",
            ) from exc
        return cls(redis.from_url(url, **kwargs), namespace=namespace)

    async def store(self, item: MemoryItem) -> None:
        item.id = item.id or uuid4().hex[:8]
        payload = {'content': item.content, 'type': item.type, 'metadata': item.metadata}
        await self.client.hset(self.namespace, item.id, json.dumps(payload))

    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        raw = await self.client.hgetall(self.namespace)
        # decode_responses 설정과 무관하게 동작한다 — json.loads는 bytes도 받고, id는 아래에서 되살린다.
        items = [
            MemoryItem(id=key.decode() if isinstance(key, bytes) else key, **json.loads(value))
            for key, value in raw.items()
        ]
        return rank(items, query, limit)

    async def delete(self, memory_id: str) -> None:
        await self.client.hdel(self.namespace, memory_id)
