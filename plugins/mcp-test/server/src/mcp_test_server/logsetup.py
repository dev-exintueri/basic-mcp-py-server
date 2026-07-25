"""로깅 구성 — 형식, 날짜 경계, 핸들러 부착.

핸들러는 mcp_test_server 로거가 아니라 **루트 로거**에 붙인다. uvicorn 의
로거는 루트로 전파되지 우리 로거로 가지 않으므로, 루트에 붙여야 서버가
내는 모든 줄이 한 파일에 모인다.

configure_logging() 은 __main__.main() 에서만 부른다. build_stack() 이
부르면 테스트가 돌 때마다 전역 로깅 상태가 오염된다.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from .logpaths import log_file_name
from .logstream import BroadcastHandler, LogBroadcaster

# logging 의 표시명을 스펙 §2 의 5칸 형식에 맞춘다.
_LEVEL_NAMES = {"WARNING": "WARN", "CRITICAL": "ERROR"}


class ClockFormatter(logging.Formatter):
    """주입된 시계로 타임스탬프를 찍는 포매터.

    record.created 를 쓰지 않는다. 그것은 time.time() 이라 주입할 수 없고,
    이 프로젝트의 전역 제약을 어긴다.
    """

    def __init__(self, clock: Callable[[], datetime]) -> None:
        super().__init__()
        self._clock = clock

    def format(self, record: logging.LogRecord) -> str:
        stamp = self._clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        level = _LEVEL_NAMES.get(record.levelname, record.levelname)
        category = record.name.rsplit(".", 1)[-1]
        line = f"{stamp} {level:<5} {category:<8} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class DailyFileHandler(logging.FileHandler):
    """하루 한 파일. 날짜 경계는 주입된 시계로 판단한다.

    stdlib 의 TimedRotatingFileHandler 를 쓰지 않는 이유는 스펙 §3.3 에
    있다 — 그쪽은 개수 기준으로 지우고 시계를 주입할 수 없다.
    """

    def __init__(self, log_dir: Path, port: int, clock: Callable[[], datetime]) -> None:
        self._log_dir = Path(log_dir)
        self._port = port
        self._clock = clock
        self._day = clock().date()
        super().__init__(self._path_for(self._day), encoding="utf-8")

    def _path_for(self, day: date) -> Path:
        return self._log_dir / log_file_name(self._port, day)

    @property
    def current_path(self) -> Path:
        return Path(self.baseFilename)

    def emit(self, record: logging.LogRecord) -> None:
        today = self._clock().date()
        if today != self._day:
            self.close()
            self._day = today
            self.baseFilename = str(self._path_for(today))
            self.stream = self._open()
        super().emit(record)


class LoggingHandle:
    """configure_logging() 이 돌려주는 손잡이. 되돌릴 수 있게 한다."""

    def __init__(
        self,
        log_dir: Path | None,
        file_handler: DailyFileHandler | None,
        broadcaster: LogBroadcaster,
        added: list[logging.Handler],
        previous_level: int,
    ) -> None:
        self.log_dir = log_dir
        self.broadcaster = broadcaster
        self._file_handler = file_handler
        self._added = added
        self._previous_level = previous_level

    @property
    def log_file(self) -> Path | None:
        """현재 쓰고 있는 파일. 날짜가 넘어가면 값이 바뀐다."""
        return self._file_handler.current_path if self._file_handler else None

    def shutdown(self) -> None:
        root = logging.getLogger()
        for handler in self._added:
            root.removeHandler(handler)
            handler.close()
        self._added.clear()
        # 루트 로거는 전역 상태다. configure_logging() 이 바꾼 레벨을
        # 여기서 되돌리지 않으면 이 프로세스에서 도는 다른 로깅이 (특히
        # 다음 테스트가) 오염된 레벨을 물려받는다.
        root.setLevel(self._previous_level)


def configure_logging(
    *,
    log_dir: Path,
    port: int,
    clock: Callable[[], datetime],
    broadcaster: LogBroadcaster,
    level: int = logging.INFO,
) -> LoggingHandle:
    """루트 로거에 파일 핸들러와 브로드캐스트 핸들러를 붙인다.

    디렉토리를 만들 수 없으면 파일 로깅만 포기한다. 서버는 뜬다 — 로그
    디렉토리 때문에 테스트 서버가 기동하지 못하는 것은 거꾸로 간 것이다.
    """
    formatter = ClockFormatter(clock)
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(level)
    added: list[logging.Handler] = []

    file_handler: DailyFileHandler | None = None
    resolved_dir: Path | None = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = DailyFileHandler(log_dir, port, clock)
    except OSError as exc:
        print(
            f"경고: 로그 디렉토리 {log_dir} 를 쓸 수 없다 ({exc}). "
            "파일 로깅 없이 계속한다.",
            file=sys.stderr,
        )
    else:
        resolved_dir = log_dir
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        added.append(file_handler)

    stream_handler = BroadcastHandler(broadcaster)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
    added.append(stream_handler)

    return LoggingHandle(resolved_dir, file_handler, broadcaster, added, previous_level)
