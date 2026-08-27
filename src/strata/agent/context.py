from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass
class Context:
    """현재 실행의 상태. 실행 종료 후 지속을 보장하지 않는다 — 영속은 Memory의 몫.

    - instructions: system 지시. messages에 섞지 않고 분리해 두어 Strategy가
      호출 시점에 덧붙일 수 있고(RLM의 환경 설명 등) child가 상속할 수 있다.
    - variables: 실행 중 상태 변수 = RLM의 Environment. 거대 입력은 messages가
      아니라 여기(`variables['context']`)에 두고 Tool(REPL)로만 접근한다.
    """

    messages: list = field(default_factory=list)
    instructions: str | None = None
    variables: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def last_assistant_text(self) -> str | None:
        """한도 초과 시 '지금까지의 결과'로 쓸 마지막 assistant 텍스트."""
        for message in reversed(self.messages):
            if message.get('role') == 'assistant' and message.get('content'):
                return message['content']
        return None
