# 4. Memory

**실행 사이에 남는 사실.** 어제 배운 것을 오늘 실행이 알게 하는 자리다.

대화 이력이 아니다 — 그건 [5. 멀티턴](05-conversation.md)이다. 둘의 차이:

| | Memory | 대화 이력 |
|---|---|---|
| 무엇 | 사실 ("사용자는 uv를 쓴다") | 원문 ("아까 뭐라고 했지?") |
| 순서 | 없음 | 있음 (순서가 의미의 일부) |
| 저장 | 모델이 명시적으로 | 자동으로 쌓임 |
| 누가 갖나 | Memory 구현 | 앱 |

## 세 가지 구현

```python
from strata import InMemory, SQLiteMemory, RedisMemory

InMemory()                                          # 개발·테스트. 프로세스가 죽으면 사라진다
SQLiteMemory('memory.db', namespace='user:42')      # 영속. stdlib sqlite3라 의존성 0
RedisMemory(client=redis_client, namespace='u:42')  # 워커가 여러 호스트에 흩어질 때
```

`RedisMemory`는 클라이언트를 **주입**받는다 — strata는 `redis`를 import하지 않는다. 연결
설정·풀 크기·인증은 앱이 이미 갖고 있는 것을 그대로 쓴다.

`InMemory`는 프로세스 로컬이다. 멀티 워커에서 쓰면 **워커마다 기억이 갈라진다.**

### 스코프는 인스턴스가 가른다

`retrieve(query, user_id=...)` 같은 인자가 없다. 대신 인스턴스를 나눈다:

```python
alice = SQLiteMemory('memory.db', namespace='user:alice')
bob   = SQLiteMemory('memory.db', namespace='user:bob')
# 같은 파일, 서로 안 보인다
```

이렇게 하면 "user_id를 안 넘겨서 남의 기억을 읽는" 사고가 구조적으로 불가능하다.

## 저장은 명시적, 조회는 자동

이 비대칭이 설계의 핵심이다.

```python
agent = Agent(
    provider=...,
    strategy=ReActStrategy(),
    memory=SQLiteMemory('memory.db', namespace='user:42'),   # ← 조회가 켜진다
    tools=[MemoryTool()],                                     # ← 저장이 켜진다
)
```

**조회는 매 `run`마다 자동으로** 일어난다. task 문자열로 검색해 상위 항목을 system 지시에
붙인다:

```
## What you remember from earlier runs
- 사용자는 uv를 쓴다
- 배포는 금요일에 하지 않는다
```

모델에게 "기억을 찾아봐"라고 시키면 안 찾는 턴이 생기고, 그러면 기억이 있는데도 모르는 채로
답한다. 그래서 자동이다.

**저장은 모델이 `remember`를 명시적으로 불러야** 한다. 자동이면 전부 저장되고, 그러면
"네 알겠습니다" 수백 개가 진짜 기억을 덮는다. 저장을 아끼는 것이 검색 품질을 지키는 방법이다.

```python
# 두 개를 따로 줄 수 있다
Agent(..., memory=mem)                        # 읽기 전용 — 앱이 관리하는 프로필을 주입만
Agent(..., memory=mem, tools=[MemoryTool()])  # 읽고 쓰기
```

## 직접 넣고 빼기

```python
from strata import MemoryItem

await mem.store(MemoryItem(content='이 사용자의 소속은 R&D센터'))
await mem.store(MemoryItem(content='배포 승인자는 팀장', type='procedural'))

items = await mem.retrieve('배포 절차', limit=5)
await mem.delete(items[0].id)
```

`MemoryItem`:

```python
MemoryItem(
    content,                 # 한 문장으로 자립적인 사실
    type='semantic',         # semantic | episodic | procedural — 코어는 해석하지 않는다
    id=None,                 # store가 채운다
    metadata={},             # 자유 dict
)
```

반드시 남아야 하는 정보는 **앱이 직접 `store`** 하라. 모델이 `remember`를 부를지는 판단이라
보장되지 않는다.

## 무엇이 검색되나

BM25로 점수를 매긴다 — 빈도, 문서 길이, 단어의 희소성을 함께 본다. 토큰이 아니라
**부분 문자열**로 세는데, 한국어가 교착어라 `'uv를' != 'uv'`로 단어 단위 비교가 거의 다
빗나가기 때문이다.

세 구현이 **같은 점수 함수**를 쓴다. 저장소를 바꿔도 "무엇이 관련 있는가"의 판단이 바뀌지
않아야 하기 때문이다.

알고 받아들인 한계 셋:

- **의미 검색이 아니다.** `'결제 실패'`로 `'구매 오류'`를 찾지 못한다. 동의어가 중요하면
  같은 `Memory` 인터페이스로 임베딩 기반 구현을 붙여라.
- **전체 스캔이다.** 20,000건에서 조회 한 번에 수십 ms. 항목이 그보다 훨씬 많아지면 아프다.
- **시간 개념이 없다.** 5초 전 사실과 1년 전 사실이 동등하다. "예전엔 vim, 지금은 vscode"가
  둘 다 저장돼 있으면 어느 쪽이 이길지 모른다. 상충하는 기억은 `delete`로 정리해야 한다.

## 직접 만들기

```python
from strata import Memory, MemoryItem
from strata.memory.base import rank        # 점수 함수를 공유하면 결과가 일관된다

class MyMemory(Memory):
    async def store(self, item: MemoryItem) -> None: ...
    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        return rank(await self._all(), query, limit)
    async def delete(self, memory_id: str) -> None: ...
```
