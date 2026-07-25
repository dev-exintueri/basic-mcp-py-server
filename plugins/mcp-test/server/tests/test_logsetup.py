"""포매터, 날짜 경계 핸들러, 로깅 구성."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp_test_server.logsetup import ClockFormatter, DailyFileHandler, configure_logging
from mcp_test_server.logstream import LogBroadcaster

START = datetime(2026, 7, 25, 23, 59, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def make_record(name: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(name, level, "path.py", 1, msg, None, None)


def test_format_matches_the_spec_shape() -> None:
    clock = FakeClock(START)
    line = ClockFormatter(clock).format(
        make_record("mcp_test_server.http", logging.INFO, "POST /mcp 200 dur_ms=12")
    )
    assert line == "2026-07-25T23:59:00Z INFO  http     POST /mcp 200 dur_ms=12"


def test_warning_is_rendered_as_WARN() -> None:
    clock = FakeClock(START)
    line = ClockFormatter(clock).format(
        make_record("mcp_test_server.http", logging.WARNING, "POST /mcp 401")
    )
    assert line.split()[1] == "WARN"


def test_uvicorn_logger_name_keeps_its_last_segment() -> None:
    clock = FakeClock(START)
    line = ClockFormatter(clock).format(make_record("uvicorn.error", logging.INFO, "started"))
    assert " error    " in line


def test_timestamp_comes_from_the_injected_clock_not_the_record() -> None:
    """record.created 는 실제 시각이다. 가짜 시계가 이겨야 한다."""
    clock = FakeClock(START)
    record = make_record("mcp_test_server.app", logging.INFO, "hello")
    assert ClockFormatter(clock).format(record).startswith("2026-07-25T23:59:00Z")


def test_exception_text_is_appended() -> None:
    clock = FakeClock(START)
    try:
        raise RuntimeError("boom-marker")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "mcp_test_server.app", logging.ERROR, "p", 1, "died", None, sys.exc_info()
        )
    line = ClockFormatter(clock).format(record)
    assert "Traceback" in line
    assert "boom-marker" in line


def test_handler_switches_file_when_the_injected_clock_crosses_midnight(
    tmp_path: Path,
) -> None:
    clock = FakeClock(START)
    handler = DailyFileHandler(tmp_path, 8765, clock)
    handler.setFormatter(ClockFormatter(clock))

    handler.emit(make_record("mcp_test_server.app", logging.INFO, "before"))
    clock.advance(minutes=2)
    handler.emit(make_record("mcp_test_server.app", logging.INFO, "after"))
    handler.close()

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [
        "mcp-test-server.8765.2026-07-25.log",
        "mcp-test-server.8765.2026-07-26.log",
    ]
    assert "before" in (tmp_path / names[0]).read_text(encoding="utf-8")
    assert "after" in (tmp_path / names[1]).read_text(encoding="utf-8")


def test_current_path_follows_the_rollover(tmp_path: Path) -> None:
    clock = FakeClock(START)
    handler = DailyFileHandler(tmp_path, 8765, clock)
    handler.setFormatter(ClockFormatter(clock))
    first = handler.current_path
    clock.advance(minutes=2)
    handler.emit(make_record("mcp_test_server.app", logging.INFO, "x"))
    assert handler.current_path != first
    handler.close()


def test_a_failed_rollover_neither_raises_nor_wedges_the_handler(tmp_path: Path) -> None:
    """회전에 실패해도 emit 은 조용히 넘어가고, 길이 열리면 스스로 회복한다.

    두 번 emit 하는 것이 이 테스트의 핵심이다. 한 번만 보면 "_day 를 먼저
    올려 두는" 구현도 통과한다 — 그 구현의 진짜 증상은 두 번째 emit 부터다.
    _day 가 이미 다음 날로 가 있으면 회전 분기를 건너뛰고 stream=None 인 채
    FileHandler.emit 으로 들어가 프로세스가 사는 내내 같은 예외를 낸다.

    막는 방법으로 chmod 를 쓰지 않는다. root 로 돌면 무시되고 뒷정리도
    번거롭다. 다음 날 파일이 놓일 **바로 그 경로에 디렉토리를 만들어** 두면
    _open() 이 어느 OS 에서나 IsADirectoryError(=OSError) 를 낸다.
    """
    clock = FakeClock(START)
    handler = DailyFileHandler(tmp_path, 8765, clock)
    handler.setFormatter(ClockFormatter(clock))
    handler.emit(make_record("mcp_test_server.app", logging.INFO, "첫날"))
    first_path = handler.current_path

    blocker = tmp_path / "mcp-test-server.8765.2026-07-26.log"
    blocker.mkdir()
    clock.advance(minutes=2)

    handler.emit(make_record("mcp_test_server.app", logging.INFO, "막힌 동안 1"))
    handler.emit(make_record("mcp_test_server.app", logging.INFO, "막힌 동안 2"))

    # 실패한 회전이 current_path 를 열리지도 않은 파일로 옮겨 놓으면 안 된다.
    # 이 값은 purge_logs(keep=...) 로 흘러가 "지우면 안 되는 파일"이 된다.
    assert handler.current_path == first_path

    blocker.rmdir()
    handler.emit(make_record("mcp_test_server.app", logging.INFO, "회복"))
    handler.close()

    assert "회복" in (tmp_path / blocker.name).read_text(encoding="utf-8")


def test_configure_logging_attaches_to_the_root_logger_so_uvicorn_is_caught(
    tmp_path: Path,
) -> None:
    # uvicorn.Config.__init__ 은 생성되는 즉시 자기 configure_logging() 을
    # 불러 logging.config.dictConfig() 로 "uvicorn" 로거에 handlers=[stderr],
    # propagate=False 를 박고 "uvicorn.error" 에는 자기 log_level 을 박는다.
    # 이 프로세스 안에서 다른 테스트(예: test_app.py)가 uvicorn.Config 를
    # 하나라도 만들었으면 그 상태가 이미 남아 있어, "uvicorn.error" 에서
    # 낸 레코드가 부모 "uvicorn" 의 propagate=False 에 막혀 루트까지
    # 못 온다. 이 테스트가 검증하려는 건 "우리 configure_logging() 이
    # 루트에 붙였으니 전파되는 건 다 잡힌다"는 실제 운영 시맨틱스이므로,
    # 제3자 라이브러리가 프로세스 전역에 남긴 이 얼룩을 걷어내고 시작한다.
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_error = logging.getLogger("uvicorn.error")
    saved = [
        (uvicorn_logger, uvicorn_logger.level, uvicorn_logger.propagate, list(uvicorn_logger.handlers)),
        (uvicorn_error, uvicorn_error.level, uvicorn_error.propagate, list(uvicorn_error.handlers)),
    ]
    for logger, *_ in saved:
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
        logger.handlers = []

    clock = FakeClock(START)
    handle = configure_logging(
        log_dir=tmp_path, port=8765, clock=clock, broadcaster=LogBroadcaster()
    )
    try:
        logging.getLogger("uvicorn.error").info("uvicorn started")
        logging.getLogger("mcp_test_server.app").info("ours")
        for h in logging.getLogger().handlers:
            h.flush()
        text = handle.log_file.read_text(encoding="utf-8")
        assert "uvicorn started" in text
        assert "ours" in text
    finally:
        handle.shutdown()
        for logger, level, propagate, handlers in saved:
            logger.setLevel(level)
            logger.propagate = propagate
            logger.handlers = handlers


def test_configure_logging_survives_an_unwritable_directory(tmp_path: Path) -> None:
    """파일 로깅만 포기하고 서버는 떠야 한다 (스펙 §4.4)."""
    blocker = tmp_path / "blocked"
    blocker.write_text("이 경로는 파일이라 디렉토리를 만들 수 없다", encoding="utf-8")

    handle = configure_logging(
        log_dir=blocker / "logs", port=8765, clock=FakeClock(START), broadcaster=LogBroadcaster()
    )
    try:
        assert handle.log_file is None
        logging.getLogger("mcp_test_server.app").info("죽지 않는다")
    finally:
        handle.shutdown()


def test_shutdown_removes_the_handlers_it_added(tmp_path: Path) -> None:
    before = list(logging.getLogger().handlers)
    handle = configure_logging(
        log_dir=tmp_path, port=8765, clock=FakeClock(START), broadcaster=LogBroadcaster()
    )
    handle.shutdown()
    assert logging.getLogger().handlers == before


def test_shutdown_restores_the_root_logger_level(tmp_path: Path) -> None:
    """configure_logging 이 root.setLevel 로 바꾼 레벨을 shutdown 이 되돌린다.

    루트 로거는 전역 상태다. 여기서 되돌리지 않으면 이 테스트 스위트의
    다른 테스트가 이 테스트 뒤에 도는지 여부에 따라 로그 레벨이 달라진다.
    """
    root = logging.getLogger()
    original_level = root.level
    handle = configure_logging(
        log_dir=tmp_path,
        port=8765,
        clock=FakeClock(START),
        broadcaster=LogBroadcaster(),
        level=logging.DEBUG,
    )
    handle.shutdown()
    assert root.level == original_level
