"""pytest 공통 설정 + 테스트 공용 fake. 실제 LLM 호출 없음.

- 저장소 루트의 .env를 환경변수로 로드한다(터미널이든 IDE든 API 키가 잡히게. .env는 gitignore).
- ScriptedProvider / TaskScriptedProvider: 모든 Strategy·Runtime 테스트가 쓰는 fake Provider.
  테스트 파일은 `from conftest import ...`로 가져온다.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from strata.providers import ModelResponse
from strata.providers import Provider
from strata.providers import ToolCall

load_dotenv(Path(__file__).parent.parent / '.env')


def call(name, **arguments):
    """tool call 하나를 담은 응답."""
    return ModelResponse(tool_calls=[ToolCall(name=name, arguments=arguments)])


def final(text):
    """tool call 없는 최종 답."""
    return ModelResponse(text=text)


class ScriptedProvider(Provider):
    """정해진 응답을 순서대로 반환한다. seen = 호출별 메시지 스냅샷, kwargs = 호출별 모델 파라미터."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []
        self.kwargs = []

    async def generate(self, messages, tools=None, **kwargs):
        self.seen.append([dict(m) for m in messages])
        self.kwargs.append(kwargs)
        if not self.responses:
            raise AssertionError('script exhausted')
        return self.responses.pop(0)


class TaskScriptedProvider(Provider):
    """task(첫 user 메시지)별 응답 스크립트 — 재귀 테스트용. seen = (task, 메시지 스냅샷).

    system 메시지가 앞에 붙을 수 있으므로 role=user 첫 메시지를 task로 본다.
    """

    def __init__(self, script):
        self.script = {task: list(responses) for task, responses in script.items()}
        self.seen = []

    async def generate(self, messages, tools=None, **kwargs):
        task = next(m['content'] for m in messages if m['role'] == 'user')
        self.seen.append((task, [dict(m) for m in messages]))
        if not self.script.get(task):
            raise AssertionError(f'script exhausted for task {task!r}')
        return self.script[task].pop(0)

    def observations(self, task):
        """해당 task의 agent가 마지막 호출까지 받은 tool 관찰 내용들(순서대로)."""
        _, messages = [s for s in self.seen if s[0] == task][-1]
        return [m['content'] for m in messages if m['role'] == 'tool']
