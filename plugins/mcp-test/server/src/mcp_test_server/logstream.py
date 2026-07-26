"""로그 줄을 SSE 구독자에게 fan-out 한다.

파일을 다시 읽지 않는다. 로깅 핸들러에서 바로 밀기 때문에 파일 회전은
스트림과 무관하고, 파일 로깅이 꺼져 있어도 스트림은 동작한다.

## 응용할 때

포크해도 대개 그대로 둔다. 고친다면 `max_queue` 정도다.

**깨면 안 되는 것.**

- 큐에는 `LogRecord` 가 아니라 포맷된 문자열을 넣는다. 이유는
  `BroadcastHandler` 독스트링에 있다.
- `publish()` 는 루프가 없거나 닫히는 중이면 조용히 버린다. 여기서
  예외를 내면 이 기능의 존재 이유인 크래시 줄이 사라진다.
- 큐가 가득 차면 오래된 것부터 버린다. 느린 브라우저가 서버를 세우면
  안 된다.
"""

from __future__ import annotations

import asyncio
import logging


class LogBroadcaster:
    """구독자 큐에 포맷된 로그 줄을 밀어 넣는다."""

    def __init__(self, max_queue: int = 1000) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._max_queue = max_queue

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """serve() 가 시작될 때 자기 루프를 알려 준다."""
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def publish(self, line: str) -> None:
        """스트림으로 한 줄 민다. 루프가 없으면 조용히 버린다.

        configure_logging() 은 asyncio.run() 전에 돈다. 기동 로그는 루프가
        생기기 전에 나고 크래시 로그는 루프가 닫힌 뒤에 날 수 있다. 여기서
        예외를 내면 logging 안에서 터져 stderr 잡음이 되거나 — 더 나쁘게는 —
        이 기능의 존재 이유인 크래시 줄이 조용히 사라진다.

        루프가 닫히는 중이면 is_closed() 가 아직 False 를 돌려준 직후에
        call_soon_threadsafe 가 RuntimeError 를 던질 수 있다. 종료 시퀀스의
        정상적인 모습이므로 삼킨다.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._fanout, line)
        except RuntimeError:
            return

    def _fanout(self, line: str) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # 느린 브라우저가 서버를 세우면 안 된다. 오래된 것부터 버린다.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(line)
            except asyncio.QueueFull:
                pass


class BroadcastHandler(logging.Handler):
    """로그 레코드를 포맷해 브로드캐스터에 넘기는 핸들러.

    큐에는 LogRecord 가 아니라 **포맷된 문자열**을 넣는다. LogRecord 는
    args 를 들고 있다가 나중에 % 보간을 하는데, 그 "나중"이 다른
    태스크가 되고 인자가 가변 객체이면 파일과 화면의 내용이 갈린다.
    """

    def __init__(self, broadcaster: LogBroadcaster) -> None:
        super().__init__()
        self._broadcaster = broadcaster

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._broadcaster.publish(self.format(record))
        except Exception:  # noqa: BLE001 - 로깅이 애플리케이션을 죽이면 안 된다
            self.handleError(record)
