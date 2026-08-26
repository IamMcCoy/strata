"""전체 파이프라인 — Redis 큐 + task_id + 멀티 워커 + Memory + Tool (ADR-0010).

실행:
    make redis-up
    uv run python examples/worker.py

OPENAI_API_KEY가 있으면 실제 LLM을, 없으면 스크립트 Provider를 쓴다(둘 다 같은 코드 경로).

여기 있는 큐 코드는 **앱의 코드지 strata의 일부가 아니다.** Agent는 직렬화할 수 없어서
(Provider는 살아있는 API 클라이언트다) 워커가 미리 들고 있어야 하고, 큐에 실리는 건
`{id, task, history}` 뿐이다. 그래서 브로커 선택은 앱의 몫이다 — Celery든 SQS든 이 자리에 들어간다.
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
from uuid import uuid4

import redis.asyncio as redis
from strata import Agent
from strata import MemoryTool
from strata import ModelResponse
from strata import OpenAIProvider
from strata import Provider
from strata import ReActStrategy
from strata import RedisMemory
from strata import Tool
from strata import ToolCall

REDIS_URL = os.environ.get('REDIS_URL', f"redis://127.0.0.1:{os.environ.get('REDIS_PORT', '6379')}")
QUEUE = 'strata:tasks'
# 모델이 지어낼 수 없는 값이어야 Memory가 답했다는 증명이 된다 — 우연히 맞을 수 없다.
# retrieve는 단어 겹침이라 조회 문장과 토큰이 겹쳐야 한다 — '계산 결과 보고'가 다리 역할을 한다.
FACT = '사용자의 계산 결과 보고 코드는 ZX-42다'
RESULT = 'strata:result:{}'


class AddTool(Tool):
    name = 'add'
    description = 'Add two integers and return their sum'
    input_schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
        'required': ['a', 'b'],
    }

    async def execute(self, env, **kwargs):
        print(f"    [tool] add({kwargs['a']}, {kwargs['b']})", flush=True)
        return kwargs['a'] + kwargs['b']


class ScriptedProvider(Provider):
    """OPENAI_API_KEY가 없을 때의 대역 — Agent/Tool/Memory 배선은 실제와 동일하게 탄다."""

    async def generate(self, messages, tools=None, **kwargs):
        system = messages[0]['content'] if messages[0]['role'] == 'system' else ''
        turns = [m for m in messages if m['role'] != 'system']
        last = turns[-1]

        if last['role'] == 'tool':
            return ModelResponse(text=f"답은 {last['content']}입니다.")
        if '더해' in last['content']:
            a, b = (int(w) for w in last['content'].split() if w.isdigit())
            return ModelResponse(tool_calls=[ToolCall(name='add', arguments={'a': a, 'b': b})])
        if '기억해' in last['content']:
            return ModelResponse(tool_calls=[ToolCall(name='remember', arguments={'content': FACT})])
        if '보고 코드' in last['content']:
            # Memory에서만 알 수 있는 것 — system 지시로 들어온 사실
            return ModelResponse(text='ZX-42입니다.' if 'ZX-42' in system else '모르겠습니다.')
        if '방금' in last['content']:
            # history에서만 알 수 있는 것 — 이전 턴의 계산 결과
            seen = ' '.join(m.get('content') or '' for m in turns)
            return ModelResponse(text='방금 결과는 42입니다.' if '42' in seen else '기록이 없습니다.')
        return ModelResponse(text='네.')


def build_provider():
    if os.environ.get('OPENAI_API_KEY'):
        return OpenAIProvider(model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'), model_params={'temperature': 0})
    return ScriptedProvider()


# --- 워커 (별개 프로세스) ---------------------------------------------------------

async def worker_loop(name: str) -> None:
    client = redis.from_url(REDIS_URL)
    # Agent는 워커가 소유한다 — 큐에 실을 수 없기 때문이다. Memory만 워커 간에 공유된다.
    agent = Agent(
        provider=build_provider(), strategy=ReActStrategy(),
        tools=[AddTool(), MemoryTool()], memory=RedisMemory(client, namespace='demo'),
    )
    try:
        while True:
            # ponytail: BLPOP은 at-most-once — 워커가 작업 중 죽으면 그 작업은 사라진다.
            # 재시도·dead-letter가 필요하면 Redis Streams(XREADGROUP)나 Celery로 간다.
            popped = await client.blpop(QUEUE, timeout=1)
            if popped is None:
                continue  # 큐가 비었을 뿐 — 계속 기다린다
            job = json.loads(popped[1])
            if job.get('stop'):  # graceful shutdown 신호
                print(f'  [{name}] 종료', flush=True)
                return
            print(f"  [{name}] 처리 시작 id={job['id']} · {job['task']!r}", flush=True)

            result = await agent.run(job['task'], history=job['history'])
            payload = {'status': result.status, 'result': result.result, 'messages': result.metadata['messages']}
            await client.setex(RESULT.format(job['id']), 3600, json.dumps(payload))
            print(f"  [{name}] 완료   id={job['id']} → {result.result!r}", flush=True)
    finally:
        await client.aclose()


def run_worker(name: str) -> None:
    asyncio.run(worker_loop(name))


# --- 클라이언트 -------------------------------------------------------------------

async def submit(client, task: str, history: list | None = None) -> str:
    """task_id를 발급하고 큐에 넣는다. HTTP API라면 여기가 `POST /tasks`다."""
    task_id = uuid4().hex[:8]
    await client.rpush(QUEUE, json.dumps({'id': task_id, 'task': task, 'history': history or []}))
    print(f'[main] enqueue id={task_id} · {task!r}', flush=True)
    return task_id


async def poll(client, task_id: str, timeout: float = 30.0) -> dict:
    """결과가 나올 때까지 조회. HTTP API라면 여기가 `GET /tasks/{id}`다."""
    # ponytail: 폴링은 HTTP API가 실제로 하는 모양이라 그대로 뒀다.
    # 즉시 통지가 필요하면 BRPOP이나 pub/sub으로 바꾼다 — 큐 키 하나만 더 쓰면 된다.
    for _ in range(int(timeout / 0.05)):
        raw = await client.get(RESULT.format(task_id))
        if raw:
            return json.loads(raw)
        await asyncio.sleep(0.05)
    raise TimeoutError(f'task {task_id} 결과가 시간 안에 오지 않았다')


async def main():
    client = redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        raise SystemExit(f'Redis({REDIS_URL})에 연결할 수 없습니다 — `make redis-up`')
    await client.flushdb()

    print(f"[main] Provider: {type(build_provider()).__name__}")
    ctx = mp.get_context('spawn')
    workers = [ctx.Process(target=run_worker, args=(f'worker-{i}',)) for i in (1, 2)]
    for w in workers:
        w.start()
    print('[main] 워커 2개 기동 (별개 프로세스)', flush=True)

    try:
        # 1) Tool — 워커의 Agent가 add를 실행한다
        calc = await poll(client, await submit(client, '12 와 30 을 더해줘'))
        print(f"[main] GET result → {calc['result']!r}\n", flush=True)

        # 2) history — 큐로 이전 턴을 실어 보낸다. 이 답은 history 없이는 못 한다.
        followup = await poll(
            client, await submit(
                client, '방금 계산 결과가 뭐였지?', history=calc['messages'],
            ),
        )
        print(f"[main] history로 답함 → {followup['result']!r}\n", flush=True)

        # 3) Memory — 한 워커가 remember, 다른 워커가 recall.
        #    history를 **주지 않는다**. 그래야 Memory가 답했다는 증명이 된다.
        await poll(client, await submit(client, '계산 결과 보고 코드가 ZX-42라는 걸 기억해'))
        recalled = await poll(client, await submit(client, '계산 결과 보고 코드가 뭐야?'))
        print(f"[main] Memory로 답함 → {recalled['result']!r}", flush=True)
        print('[main] ↑ history 없이 답했다 — Memory가 워커 경계를 넘었다', flush=True)

        assert '42' in (calc['result'] or ''), calc
        assert '42' in (followup['result'] or ''), followup
        assert 'ZX-42' in (recalled['result'] or ''), recalled  # 모델이 지어낼 수 없는 값
        print('\n[main] 파이프라인 OK — task_id 발급 → 큐 → 워커 → 결과 조회', flush=True)
    finally:
        for _ in workers:  # 워커 수만큼 종료 신호를 넣는다
            await client.rpush(QUEUE, json.dumps({'stop': True}))
        for w in workers:
            w.join(timeout=15)
            if w.is_alive():
                w.terminate()
        await client.aclose()


if __name__ == '__main__':
    asyncio.run(main())
