"""SSE 브로드캐스터와 그 로깅 핸들러."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from mcp_test_server.logstream import BroadcastHandler, LogBroadcaster


def make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("mcp_test_server.app", logging.INFO, "p", 1, msg, None, None)


# --- 루프가 없을 때 (스펙 §6.2) ---
#
# 이 테스트는 반드시 동기 함수여야 한다. 이 저장소는 asyncio_mode = "auto"
# 라서 async def 테스트에는 항상 실행 중인 루프가 있고, 그러면 아무것도
# 증명하지 못한다.


def test_publish_without_a_loop_does_not_raise() -> None:
    LogBroadcaster().publish("루프가 없다")


def test_file_handler_still_writes_when_the_broadcaster_has_no_loop(
    tmp_path: Path,
) -> None:
    """BroadcastHandler의 emit이 루프 없이도 예외를 발생시키지 않고 처리해
    로깅 체인을 중단하지 않는다. 기동 로그와 크래시 로그는 loop 없이 나가기
    때문에 이들이 파일에 기록되는 것이 중요하다."""
    log_path = tmp_path / "out.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    stream_handler = BroadcastHandler(LogBroadcaster())    # bind_loop 를 부르지 않았다

    logger = logging.getLogger("test_no_loop")
    logger.handlers = [file_handler, stream_handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info("루프 없이도 남아야 한다")
    file_handler.close()

    assert "루프 없이도 남아야 한다" in log_path.read_text(encoding="utf-8")


def test_publish_after_the_loop_is_closed_does_not_raise() -> None:
    loop = asyncio.new_event_loop()
    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(loop)
    loop.close()
    broadcaster.publish("닫힌 뒤")


# --- 구독 ---


async def test_subscriber_receives_published_lines() -> None:
    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()

    broadcaster.publish("첫 줄")
    await asyncio.sleep(0)          # call_soon_threadsafe 가 돌 기회를 준다

    assert await asyncio.wait_for(queue.get(), timeout=1.0) == "첫 줄"
    broadcaster.unsubscribe(queue)


async def test_unsubscribe_leaves_no_subscribers() -> None:
    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()
    assert broadcaster.subscriber_count == 1
    broadcaster.unsubscribe(queue)
    assert broadcaster.subscriber_count == 0


async def test_unsubscribe_is_idempotent() -> None:
    broadcaster = LogBroadcaster()
    queue = broadcaster.subscribe()
    broadcaster.unsubscribe(queue)
    broadcaster.unsubscribe(queue)


async def test_slow_subscriber_drops_oldest_instead_of_blocking() -> None:
    broadcaster = LogBroadcaster(max_queue=2)
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()

    for i in range(5):
        broadcaster.publish(f"line{i}")
    await asyncio.sleep(0)

    drained = [queue.get_nowait() for _ in range(queue.qsize())]
    assert drained == ["line3", "line4"]


async def test_handler_publishes_formatted_strings_not_records() -> None:
    """LogRecord 를 넘기면 나중에 다른 곳에서 % 보간이 일어나 파일과 화면이 갈린다."""
    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()

    handler = BroadcastHandler(broadcaster)
    handler.setFormatter(logging.Formatter("PREFIX %(message)s"))
    logger = logging.getLogger("test_formatted")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info("값 %s", 42)
    await asyncio.sleep(0)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received == "PREFIX 값 42"
    assert isinstance(received, str)


async def test_multiple_subscribers_each_receive_published_line() -> None:
    """여러 구독자가 각각 같은 줄을 받는다. fan-out 이 동작함을 증명한다."""
    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue1 = broadcaster.subscribe()
    queue2 = broadcaster.subscribe()
    queue3 = broadcaster.subscribe()

    broadcaster.publish("공중파")
    await asyncio.sleep(0)

    assert await asyncio.wait_for(queue1.get(), timeout=1.0) == "공중파"
    assert await asyncio.wait_for(queue2.get(), timeout=1.0) == "공중파"
    assert await asyncio.wait_for(queue3.get(), timeout=1.0) == "공중파"
