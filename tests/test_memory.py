"""Phase 4 — Memory lifecycle. 실행 A에서 store한 정보가 실행 B의 Context에 주입되는지."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

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


def make_agent(provider, memory, instructions=None):
    return Agent(
        provider=provider,
        strategy=ReActStrategy(),
        tools=[MemoryTool()],
        memory=memory,
        instructions=instructions,
    )


def system_of(provider, index=0):
    """해당 provider 호출에서 모델이 실제로 받은 system 메시지."""
    first = provider.seen[index][0]
    return first['content'] if first['role'] == 'system' else ''


def test_store_in_run_a_is_recalled_in_run_b():
    memory = InMemory()

    writer = ScriptedProvider([call('remember', content=FACT), final('기억해뒀습니다')])
    assert asyncio.run(make_agent(writer, memory).run('앞으로 uv를 쓴다는 걸 기억해')).status == 'completed'
    assert [i.content for i in memory.items.values()] == [FACT]

    reader = ScriptedProvider([final('uv로 설치하세요')])
    asyncio.run(make_agent(reader, memory).run('패키지 설치는 어떻게 해?'))
    assert FACT in system_of(reader)


def test_recall_keeps_user_instructions_and_survives_empty_memory():
    memory = InMemory()
    provider = ScriptedProvider([final('ok'), final('ok')])

    asyncio.run(make_agent(provider, memory, instructions='너는 조수다').run('무관한 질문'))
    assert '너는 조수다' in system_of(provider) and 'remember from earlier runs' not in system_of(provider)

    asyncio.run(memory.store(MemoryItem(content=FACT)))
    asyncio.run(make_agent(provider, memory, instructions='너는 조수다').run('uv 얘기'))
    assert '너는 조수다' in system_of(provider, 1) and FACT in system_of(provider, 1)


def test_inmemory_ranks_by_overlap_and_deletes():
    memory = InMemory()
    for content in ('커피를 좋아한다', 'uv로 패키지를 설치한다', 'uv.lock을 커밋한다'):
        asyncio.run(memory.store(MemoryItem(content=content)))

    hits = asyncio.run(memory.retrieve('uv 패키지', limit=2))
    assert len(hits) == 2 and all('uv' in h.content for h in hits)
    assert hits[0].content == 'uv로 패키지를 설치한다'  # 'uv'+'패키지' 2점 > 'uv' 1점

    asyncio.run(memory.delete(hits[0].id))
    assert [h.content for h in asyncio.run(memory.retrieve('uv 패키지'))] == ['uv.lock을 커밋한다']


def test_tool_without_memory_reports_instead_of_crashing():
    provider = ScriptedProvider([call('remember', content=FACT), final('저장 못 했습니다')])
    result = asyncio.run(make_agent(provider, memory=None).run('기억해'))
    assert result.status == 'completed'
    assert 'No memory' in provider.seen[-1][-1]['content']


class FakeRedis:
    """redis.asyncio.Redis의 hash 명령 3개만 흉내낸다 — 서버 없이 계약을 검증하기 위해.

    실제 redis처럼 bytes를 돌려준다(decode_responses=False 기본값): 그 경로가 안 깨지는지가 중요하다.
    """

    def __init__(self, store=None):
        self.store = store if store is not None else {}  # 공유하면 '다른 워커'가 된다

    async def hset(self, key, field, value):
        self.store.setdefault(key, {})[field.encode()] = value.encode()

    async def hgetall(self, key):
        return dict(self.store.get(key, {}))

    async def hdel(self, key, field):
        self.store.get(key, {}).pop(field.encode(), None)


def memories(tmp):
    """세 구현을 같은 계약으로 검증하기 위한 factory 목록."""
    return [
        ('InMemory', lambda: InMemory()),
        ('SQLiteMemory', lambda: SQLiteMemory(str(tmp / 'contract.db'), namespace='c')),
        ('RedisMemory', lambda: RedisMemory(FakeRedis(), namespace='c')),
    ]


def test_all_implementations_satisfy_the_same_contract():
    """ABC 검증 — 저장소가 dict든 파일이든 Redis든 store/retrieve/delete가 똑같이 동작해야 한다."""
    with tempfile.TemporaryDirectory() as d:
        for name, make in memories(Path(d)):
            memory = make()
            for content in ('커피를 좋아한다', 'uv로 패키지를 설치한다', 'uv.lock을 커밋한다'):
                asyncio.run(memory.store(MemoryItem(content=content)))

            hits = asyncio.run(memory.retrieve('uv 패키지', limit=2))
            assert [h.content for h in hits] == ['uv로 패키지를 설치한다', 'uv.lock을 커밋한다'], name
            assert all(h.id for h in hits), f'{name}: id가 되살아나지 않으면 delete를 못 한다'
            assert hits[0].type == 'semantic', name

            asyncio.run(memory.delete(hits[0].id))
            assert [h.content for h in asyncio.run(memory.retrieve('uv 패키지'))] == ['uv.lock을 커밋한다'], name


def test_sqlite_survives_process_restart():
    """InMemory가 못 하는 것 — 연결(=프로세스)이 끊겨도 파일에 남는다."""
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / 'persist.db')
        first = SQLiteMemory(path)
        asyncio.run(first.store(MemoryItem(content=FACT)))
        first.close()

        reopened = SQLiteMemory(path)  # 새 프로세스가 같은 파일을 여는 것과 같다
        assert [h.content for h in asyncio.run(reopened.retrieve('uv'))] == [FACT]
        reopened.close()


def test_namespace_is_the_scope_boundary():
    """사용자·세션 격리는 retrieve 인자가 아니라 인스턴스로 가른다."""
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / 'ns.db')
        alice, bob = SQLiteMemory(path, namespace='user:alice'), SQLiteMemory(path, namespace='user:bob')
        asyncio.run(alice.store(MemoryItem(content=FACT)))
        assert [h.content for h in asyncio.run(alice.retrieve('uv'))] == [FACT]
        assert asyncio.run(bob.retrieve('uv')) == []  # 같은 파일, 다른 스코프

        shared = {}
        red_a = RedisMemory(FakeRedis(shared), namespace='user:alice')
        red_b = RedisMemory(FakeRedis(shared), namespace='user:bob')
        asyncio.run(red_a.store(MemoryItem(content=FACT)))
        assert asyncio.run(red_b.retrieve('uv')) == []
        alice.close()
        bob.close()


def test_redis_shares_across_workers():
    """멀티 워커의 핵심 — 워커 A가 저장한 걸 워커 B가 읽는다 (InMemory가 못 하는 것)."""
    backend = {}  # 같은 Redis 서버
    worker_a = RedisMemory(FakeRedis(backend))
    worker_b = RedisMemory(FakeRedis(backend))  # 별개 프로세스의 별개 클라이언트
    asyncio.run(worker_a.store(MemoryItem(content=FACT)))
    assert [h.content for h in asyncio.run(worker_b.retrieve('uv'))] == [FACT]


def test_agent_works_with_any_implementation():
    """Agent/MemoryTool은 구현을 모른다 — 갈아끼워도 lifecycle이 그대로 돈다."""
    with tempfile.TemporaryDirectory() as d:
        for name, make in [
            ('SQLiteMemory', lambda: SQLiteMemory(str(Path(d) / 'agent.db'))),
            ('RedisMemory', lambda: RedisMemory(FakeRedis())),
        ]:
            memory = make()
            writer = ScriptedProvider([call('remember', content=FACT), final('기억해뒀습니다')])
            asyncio.run(make_agent(writer, memory).run('기억해'))

            reader = ScriptedProvider([final('uv로 설치하세요')])
            asyncio.run(make_agent(reader, memory).run('패키지 설치는 어떻게 해?'))
            assert FACT in system_of(reader), name


if __name__ == '__main__':
    test_store_in_run_a_is_recalled_in_run_b()
    test_recall_keeps_user_instructions_and_survives_empty_memory()
    test_inmemory_ranks_by_overlap_and_deletes()
    test_tool_without_memory_reports_instead_of_crashing()
    test_all_implementations_satisfy_the_same_contract()
    test_sqlite_survives_process_restart()
    test_namespace_is_the_scope_boundary()
    test_redis_shares_across_workers()
    test_agent_works_with_any_implementation()
    print('memory ok')


def ranked(contents, query, limit=10):
    memory = InMemory()
    for content in contents:
        asyncio.run(memory.store(MemoryItem(content=content)))
    return [hit.content for hit in asyncio.run(memory.retrieve(query, limit=limit))]


def test_ranking_does_not_collapse_into_insertion_order():
    """회귀: 단순 겹침은 점수 상한이 질의 단어 수(여기선 3)라 동점이 대량 발생하고,
    안정 정렬이 그것을 '가장 먼저 저장된 것'으로 잘랐다 — 더 관련 있는 항목이 나중에
    저장되면 영원히 묻혔다. 항목 10건에서도 나타난다."""
    filler = ' 그밖에 이런저런 잡담과 무관한 문장이 길게 이어진다' * 3
    contents = [f'결제 관련 작업 {i}{filler}' for i in range(10)]
    contents.append('결제 관련 작업 결제 관련 작업')  # 마지막에 저장된, 짧고 집중된 항목
    top = ranked(contents, '결제 관련 작업', limit=3)
    assert top[0] == '결제 관련 작업 결제 관련 작업'


def test_frequency_beats_a_single_mention():
    """`in`은 bool이라 한 번 나오나 열 번 나오나 같은 점수였다."""
    top = ranked(['uv 이야기', 'uv uv uv 로 uv 를 쓴다'], 'uv')
    assert top[0] == 'uv uv uv 로 uv 를 쓴다'


def test_rare_word_outweighs_a_common_one():
    """흔한 단어('작업')와 희소한 단어('롤백')가 같은 1점이면 관련 없는 항목이 올라온다."""
    contents = [f'일상 작업 기록 {i}' for i in range(8)] + ['롤백 절차 메모']
    top = ranked(contents, '롤백 작업')
    assert top[0] == '롤백 절차 메모'


def test_shorter_item_wins_on_equal_evidence():
    """길이 정규화 — 긴 항목이 우연히 히트할 확률만으로 이기면 안 된다."""
    # 긴 쪽을 먼저 저장한다 — 그래야 옛 점수(동점 → 삽입 순서)로는 긴 쪽이 이긴다
    top = ranked(['uv ' + '무관한 잡담 ' * 40, 'uv 설치'], 'uv')
    assert top[0] == 'uv 설치'


def test_items_without_any_query_word_are_dropped():
    """계약은 그대로 — 하나도 안 걸리는 항목은 결과에 없다."""
    assert ranked(['커피를 좋아한다', 'uv로 패키지를 설치한다'], 'uv') == ['uv로 패키지를 설치한다']
