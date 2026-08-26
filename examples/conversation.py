"""멀티턴 대화 + Memory 층 — 대화 이력은 앱이, 사실은 Memory가 (ADR-0010).

실행: uv run python examples/conversation.py

턴 1~2: history로 대화가 이어진다 — '거기'가 무엇인지 모델이 안다.
턴 3:   대화를 전부 잘라내도, 그 전에 remember로 남긴 사실은 Memory에서 되살아난다.
"""
from __future__ import annotations

import asyncio

from strata import Agent
from strata import InMemory
from strata import MemoryTool
from strata import ModelResponse
from strata import Provider
from strata import ReActStrategy
from strata import ToolCall

# 남길 가치가 있는 건 "무슨 말을 했나"가 아니라 "앞으로 어떻게 답해야 하나"다.
FACT = '사용자는 서울에 살아서 날씨 질문은 서울 기준으로 답한다'


class ScriptedProvider(Provider):
    """LLM 흉내 — 받은 messages와 system 지시를 보고 정해진 반응을 한다."""

    async def generate(self, messages, tools=None, **kwargs):
        system = messages[0]['content'] if messages[0]['role'] == 'system' else ''
        turns = [m for m in messages if m['role'] != 'system']
        last = turns[-1]

        if last['role'] == 'tool':
            return ModelResponse(text='기억해뒀습니다.')
        if '서울' in last['content']:
            return ModelResponse(tool_calls=[ToolCall(name='remember', arguments={'content': FACT})])
        if '거기' in last['content']:
            # history가 없으면 '거기'를 풀 수 없다 — 이전 턴을 되짚는다
            said = any(m['role'] == 'user' and '서울' in m['content'] for m in turns)
            return ModelResponse(text='서울 날씨는 맑습니다.' if said else '어디 말씀이신가요?')
        if FACT in system:
            return ModelResponse(text='서울 날씨는 맑습니다.')  # Memory가 알려준 기준
        return ModelResponse(text='어느 지역 날씨를 알려드릴까요?')


class DB:
    """앱의 저장소 자리 — 코어가 아니라 여기가 대화를 소유한다 (ADR-0010)."""

    def __init__(self):
        self.sessions: dict[str, list] = {}

    def load(self, sid: str, keep: int | None = None) -> list:
        """keep은 이어붙일 최근 메시지 수. 잘라내기 정책은 코어가 아니라 앱의 몫이다."""
        history = self.sessions.get(sid, [])
        if keep is None:
            return history
        return history[-keep:] if keep else []  # keep=0 → []. history[-0:]는 전체가 되므로 쓰지 않는다.

    def save(self, sid: str, messages: list) -> None:
        self.sessions[sid] = messages


async def main():
    db, memory = DB(), InMemory()

    async def turn(task: str, keep: int | None = None) -> str:
        agent = Agent(
            provider=ScriptedProvider(), strategy=ReActStrategy(),
            tools=[MemoryTool()], memory=memory,
        )
        result = await agent.run(task, history=db.load('s1', keep))
        db.save('s1', result.metadata['messages'])
        return result.result

    print('턴 1:', await turn('나는 서울에 살아'))
    print('턴 2:', await turn('거기 날씨 어때?'))
    print(f'      history {len(db.load("s1"))}개 · Memory {len(memory.items)}개')

    answer = await turn('날씨 알려줘', keep=0)  # 대화를 전부 잘라냈다
    print('턴 3:', answer)
    print('      ↑ history는 비었는데도 답했다 — Memory가 기준을 되살렸다')

    assert '서울' in answer, 'Memory 없이는 지역을 알 수 없어야 정상'


if __name__ == '__main__':
    asyncio.run(main())
