# 서버 로깅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP 테스트 서버가 파일로 로그를 남기고, 72시간 보관하며, 관리 화면에서 실시간으로 보이게 한다.

**Architecture:** 로깅은 루트 로거에 핸들러 둘(파일, 브로드캐스트)을 붙여 구성한다. 파일 핸들러는 주입된 시계로 날짜 경계를 판단하고, 브로드캐스트 핸들러는 SSE 구독자에게 fan-out한다. 접근 로그는 `AuthMiddleware` **바깥**의 새 미들웨어가 담당해 거부된 요청(401/403)도 잡는다. 보관 청소는 기존 `_purge_loop`에 얹는다.

**Tech Stack:** Python 3.12, stdlib `logging`, Starlette, uvicorn, pytest (`asyncio_mode = "auto"`), `uv`

**스펙:** [docs/superpowers/specs/2026-07-25-server-logging-design.md](../specs/2026-07-25-server-logging-design.md) — 결정의 근거는 전부 여기 있다. 이 계획은 그것을 코드로 옮긴 것이다.

**작업 디렉토리:** 모든 경로는 `plugins/mcp-test/server/`를 기준으로 한다. 테스트는 그 디렉토리에서 `uv run pytest`로 돌린다.

## Global Constraints

- **시간을 쓰는 코드는 `clock: Callable[[], datetime]`을 주입받는다.** `datetime.now()`를 직접 부르지 않는다. 기본값 `_utcnow`는 `app.py`에만 있다. (예외: 소요 시간 측정은 `time.monotonic()`을 쓴다 — 벽시계가 아니다.)
- **타임스탬프는 전부 UTC.** 형식은 `%Y-%m-%dT%H:%M:%SZ`.
- **미들웨어는 순수 ASGI다.** `BaseHTTPMiddleware`를 쓰지 않는다. 스트리밍 응답과 얽히기 때문이다.
- **`scope["type"] != "http"`이면 즉시 위임한다.** `lifespan` 스코프가 통과하지 못하면 인수 테스트 전부가 멈춘다.
- **`configure_logging()`은 `__main__.main()`에서만 부른다.** `build_stack()`이나 `build_admin_app()`이 부르지 않는다. 테스트가 전역 로깅 상태를 오염시키지 않게 하려는 것이다.
- **로그 보관은 나이 기준 72시간**(`259200`초). 개수 기준이 아니다.
- **기본 로그 디렉토리는 `~/.mcp-test-server/logs`.**
- **로그 파일명은 `mcp-test-server.<port>.<YYYY-MM-DD>.log`.** 청소는 이 글롭에 맞는 파일만 건드린다.
- **주석과 문서 문자열은 한국어로 쓴다.** 기존 코드의 밀도와 어조를 따른다.
- **커밋 메시지는 한국어**, 기존 형식(`feat:`, `fix:`, `test:`, `docs:`)을 따른다.
- 파이썬 버전 하한은 `>=3.11`. 새 의존성을 추가하지 않는다 — 전부 stdlib과 이미 있는 Starlette로 한다.

## 검증된 사실

계획 작성 중 실제로 돌려 확인한 것들이다. 구현자는 이것을 다시 의심할 필요가 없다.

- `functools.wraps`로 감싼 함수를 `@mcp.tool()`에 넘겨도 FastMCP는 스키마를 올바로 만든다. `ctx: Context` 인자는 스키마에서 제외된다.
- 바깥 순수 ASGI 미들웨어가 넘겨준 `send` 래퍼는 `AuthMiddleware`가 조기 `return`으로 보내는 401도 그대로 포착한다.
- `uvicorn.Config(..., log_config=None, access_log=False)`는 유효하며, 그때 `uvicorn.error`는 핸들러가 비어 있고 `propagate=True`다 — 루트 핸들러가 흡수한다.
- `logging.handlers.TimedRotatingFileHandler.getFilesToDelete()`는 파일명을 정렬해 **개수**로 자른다. 나이 기준이 아니다. (그래서 쓰지 않는다.)

## 파일 구조

| 파일 | 책임 | 작업 |
|---|---|---|
| `src/mcp_test_server/logpaths.py` | 경로 해석, 파일명 규칙, 72시간 청소, 파일 꼬리 읽기 | Task 1 (신규) |
| `src/mcp_test_server/logsetup.py` | `ClockFormatter`, `DailyFileHandler`, `configure_logging` | Task 2 (신규) |
| `src/mcp_test_server/logstream.py` | `LogBroadcaster`, `BroadcastHandler` | Task 3 (신규) |
| `src/mcp_test_server/access.py` | `AccessLogMiddleware` | Task 4 (신규) |
| `src/mcp_test_server/auth.py` | `mask_secret`, `scope["mcp_test_auth"]` 기록 | Task 4 (수정) |
| `src/mcp_test_server/mcp_server.py` | 도구 호출 로그 | Task 5 (수정) |
| `src/mcp_test_server/app.py` | 배선, 크래시 핸들러, 로그 청소 | Task 6 (수정) |
| `src/mcp_test_server/__main__.py` | `--log-dir`, `configure_logging`, `BaseException` | Task 6 (수정) |
| `src/mcp_test_server/admin.py` | 로그 영역, SSE, 세션 프래그먼트, `/api/status` | Task 7 (수정) |
| `.claude-plugin/plugin.json`, `README.md` | 플러그인 설정 항목, 문서 | Task 8 (수정) |

의존 방향은 한 방향이다. `logpaths` ← `logsetup` → `logstream`; `auth` ← `access`; `app`이 전부를 조립한다. `admin`은 `logsetup`을 import하지 않는다 — 브로드캐스터와 콜러블만 주입받는다.

---

### Task 1: `logpaths.py` — 경로 해석과 보관 청소

**Files:**
- Create: `src/mcp_test_server/logpaths.py`
- Test: `tests/test_logpaths.py`

**Interfaces:**
- Consumes: 없음 (stdlib만)
- Produces:
  - `DEFAULT_LOG_DIR: Path` — `Path.home() / ".mcp-test-server" / "logs"`
  - `MAX_AGE_SECONDS: float` — `259200.0`
  - `LOG_GLOB: str` — `"mcp-test-server.*.log"`
  - `resolve_log_dir(*, flag: str | None, env: str | None, settings_path: Path) -> tuple[Path, list[str]]` — 결정된 디렉토리와, 남겨야 할 경고 문자열 목록
  - `log_file_name(port: int, day: date) -> str`
  - `purge_logs(log_dir: Path, now: datetime, *, max_age_seconds: float = MAX_AGE_SECONDS, keep: Path | None = None) -> tuple[int, list[str]]` — 지운 개수와 경고 목록
  - `tail_lines(path: Path, *, lines: int = 200, max_bytes: int = 65536) -> list[str]`

경고를 반환하고 직접 로깅하지 않는 이유: 이 함수들은 `configure_logging()`보다 **먼저** 돈다. 로그 디렉토리를 정해야 파일 핸들러를 만들 수 있기 때문이다. 그 시점에는 남길 곳이 없으므로 호출자에게 돌려주고, 호출자가 로깅이 준비된 뒤에 남긴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_logpaths.py`:

```python
"""로그 경로 해석과 보관 청소."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mcp_test_server.logpaths import (
    DEFAULT_LOG_DIR,
    log_file_name,
    purge_logs,
    resolve_log_dir,
    tail_lines,
)

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def write_settings(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def settings_with(tmp_path: Path, log_dir: object) -> Path:
    return write_settings(
        tmp_path,
        {"pluginConfigs": {"mcp-test@basic-mcp-py-server": {"options": {"log_dir": log_dir}}}},
    )


# --- 우선순위 ---


def test_flag_wins_over_everything(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "/from/settings")
    chosen, warnings = resolve_log_dir(
        flag="/from/flag", env="/from/env", settings_path=settings
    )
    assert chosen == Path("/from/flag")
    assert warnings == []


def test_env_wins_over_settings(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "/from/settings")
    chosen, _ = resolve_log_dir(flag=None, env="/from/env", settings_path=settings)
    assert chosen == Path("/from/env")


def test_settings_wins_over_default(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "/from/settings")
    chosen, _ = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == Path("/from/settings")


def test_default_when_nothing_else(tmp_path: Path) -> None:
    chosen, warnings = resolve_log_dir(
        flag=None, env=None, settings_path=tmp_path / "absent.json"
    )
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []          # 파일이 없는 것은 정상이다


def test_tilde_and_relative_are_expanded(tmp_path: Path) -> None:
    chosen, _ = resolve_log_dir(flag="~/somewhere", env=None, settings_path=tmp_path / "x")
    assert chosen.is_absolute()
    assert "~" not in str(chosen)


# --- settings.json 실패 모드 (스펙 §4.3) ---


def test_broken_json_falls_back_and_warns(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=path)
    assert chosen == DEFAULT_LOG_DIR
    assert len(warnings) == 1


def test_missing_plugin_configs_key_is_silent(tmp_path: Path) -> None:
    settings = write_settings(tmp_path, {"model": "opus"})
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


def test_no_matching_plugin_id_is_silent(tmp_path: Path) -> None:
    settings = write_settings(
        tmp_path, {"pluginConfigs": {"other@market": {"options": {"log_dir": "/x"}}}}
    )
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


def test_matching_key_without_options_is_silent(tmp_path: Path) -> None:
    """설치했으나 이 항목만 미설정한 정상 상태다. 실패로 취급하지 않는다."""
    settings = write_settings(tmp_path, {"pluginConfigs": {"mcp-test@m": {"options": {}}}})
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


def test_two_matching_ids_picks_sorted_first_and_warns(tmp_path: Path) -> None:
    settings = write_settings(
        tmp_path,
        {
            "pluginConfigs": {
                "mcp-test@zzz": {"options": {"log_dir": "/from/zzz"}},
                "mcp-test@aaa": {"options": {"log_dir": "/from/aaa"}},
            }
        },
    )
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == Path("/from/aaa")
    assert len(warnings) == 1
    assert "mcp-test@aaa" in warnings[0]


def test_blank_log_dir_falls_back_and_warns(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "   ")
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert len(warnings) == 1


def test_non_string_log_dir_falls_back_and_warns(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, 42)
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert len(warnings) == 1


def test_null_log_dir_is_silent(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, None)
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


# --- 파일명 ---


def test_log_file_name_carries_port_and_utc_date() -> None:
    assert log_file_name(8765, date(2026, 7, 25)) == "mcp-test-server.8765.2026-07-25.log"


# --- 보관 청소 ---


def aged(path: Path, now: datetime, hours: float) -> Path:
    path.write_text("x", encoding="utf-8")
    stamp = (now - timedelta(hours=hours)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_purge_deletes_only_files_older_than_72h(tmp_path: Path) -> None:
    old = aged(tmp_path / "mcp-test-server.8765.2026-07-22.log", NOW, 73)
    fresh = aged(tmp_path / "mcp-test-server.8765.2026-07-24.log", NOW, 24)

    removed, warnings = purge_logs(tmp_path, NOW)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
    assert warnings == []


def test_purge_ignores_files_that_are_not_ours(tmp_path: Path) -> None:
    """log_dir 은 사용자가 지정한다. 홈 디렉토리를 가리켜도 안전해야 한다."""
    stranger = aged(tmp_path / "taxes.pdf", NOW, 500)
    also = aged(tmp_path / "mcp-test-server.log", NOW, 500)   # 글롭에 맞지 않는다
    nested = tmp_path / "sub"
    nested.mkdir()
    deep = aged(nested / "mcp-test-server.1.2020-01-01.log", NOW, 500)  # 비재귀

    removed, _ = purge_logs(tmp_path, NOW)

    assert removed == 0
    assert stranger.exists()
    assert also.exists()
    assert deep.exists()


def test_purge_never_deletes_the_open_file(tmp_path: Path) -> None:
    current = aged(tmp_path / "mcp-test-server.8765.2026-07-20.log", NOW, 500)

    removed, _ = purge_logs(tmp_path, NOW, keep=current)

    assert removed == 0
    assert current.exists()


def test_purge_covers_other_ports(tmp_path: Path) -> None:
    aged(tmp_path / "mcp-test-server.9999.2026-07-01.log", NOW, 500)
    removed, _ = purge_logs(tmp_path, NOW)
    assert removed == 1


def test_purge_on_missing_directory_is_quiet(tmp_path: Path) -> None:
    removed, warnings = purge_logs(tmp_path / "absent", NOW)
    assert removed == 0
    assert warnings == []


# --- 꼬리 읽기 ---


def test_tail_returns_last_n_lines(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("\n".join(f"line{i}" for i in range(500)), encoding="utf-8")
    assert tail_lines(path, lines=3) == ["line497", "line498", "line499"]


def test_tail_drops_the_partial_first_line_when_truncated(tmp_path: Path) -> None:
    path = tmp_path / "b.log"
    path.write_text("A" * 100 + "\n" + "B" * 100, encoding="utf-8")
    result = tail_lines(path, lines=10, max_bytes=50)
    assert result == ["B" * 100]      # 잘린 A 줄은 버린다


def test_tail_on_missing_file_returns_empty(tmp_path: Path) -> None:
    assert tail_lines(tmp_path / "absent.log") == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_logpaths.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.logpaths'`

- [ ] **Step 3: 구현한다**

`src/mcp_test_server/logpaths.py`:

```python
"""로그 파일의 위치와 이름, 그리고 오래된 파일 청소.

여기 있는 함수들은 configure_logging() 보다 먼저 돈다 — 디렉토리를 정해야
파일 핸들러를 만들 수 있기 때문이다. 그래서 경고를 직접 로깅하지 않고
문자열 목록으로 돌려주고, 호출자가 로깅이 준비된 뒤에 남긴다.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".mcp-test-server" / "logs"
MAX_AGE_SECONDS = 259200.0          # 72시간
LOG_GLOB = "mcp-test-server.*.log"

# 플러그인 ID는 <plugin-name>@<marketplace-name> 이다. 서버는 자기가 어느
# 마켓플레이스에서 설치됐는지 알 수 없으므로 접두사로만 맞춘다.
_PLUGIN_ID_PREFIX = "mcp-test@"

DEFAULT_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _clean(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _from_settings(settings_path: Path) -> tuple[Path | None, list[str]]:
    """Claude Code 사용자 설정에서 log_dir 을 읽는다.

    비민감 userConfig 값은 Claude Code 가 pluginConfigs[<plugin-id>].options
    에 직접 쓴다 (docs/claude-base/settings.md:816-834). 중계 파일도 훅도
    필요 없다.
    """
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except OSError:
        return None, []              # 파일이 없는 것은 정상이다

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, [f"{settings_path} 를 JSON 으로 읽지 못했다. 로그 경로 설정을 건너뛴다"]

    configs = data.get("pluginConfigs") if isinstance(data, dict) else None
    if not isinstance(configs, dict):
        return None, []

    matches = sorted(k for k in configs if k.startswith(_PLUGIN_ID_PREFIX))
    if not matches:
        return None, []

    warnings: list[str] = []
    chosen_key = matches[0]
    if len(matches) > 1:
        warnings.append(
            f"플러그인 설정이 {len(matches)}개 발견됐다. {chosen_key} 를 쓴다"
        )

    options = configs[chosen_key].get("options") if isinstance(configs[chosen_key], dict) else None
    if not isinstance(options, dict) or "log_dir" not in options:
        return None, warnings

    value = options["log_dir"]
    if value is None:
        return None, warnings
    if not isinstance(value, str):
        warnings.append(f"플러그인 설정의 log_dir 이 문자열이 아니다: {value!r}")
        return None, warnings
    if not value.strip():
        warnings.append("플러그인 설정의 log_dir 이 비어 있다")
        return None, warnings

    return _clean(value), warnings


def resolve_log_dir(
    *,
    flag: str | None,
    env: str | None,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> tuple[Path, list[str]]:
    """로그 디렉토리를 정한다. 앞이 이긴다.

    --log-dir > $MCP_TEST_LOG_DIR > settings.json > 기본값
    """
    if flag and flag.strip():
        return _clean(flag), []
    if env and env.strip():
        return _clean(env), []

    from_settings, warnings = _from_settings(settings_path)
    if from_settings is not None:
        return from_settings, warnings
    return DEFAULT_LOG_DIR, warnings


def log_file_name(port: int, day: date) -> str:
    return f"mcp-test-server.{port}.{day.isoformat()}.log"


def purge_logs(
    log_dir: Path,
    now: datetime,
    *,
    max_age_seconds: float = MAX_AGE_SECONDS,
    keep: Path | None = None,
) -> tuple[int, list[str]]:
    """72시간보다 오래된 로그 파일을 지운다. 지운 개수와 경고를 돌려준다.

    LOG_GLOB 에 맞는 파일만, 비재귀로 본다. log_dir 은 사용자가 지정할 수
    있으므로 무관한 파일을 지워서는 안 된다 — 홈 디렉토리를 가리켜도
    안전해야 한다.
    """
    cutoff = now.timestamp() - max_age_seconds
    keep_resolved = keep.resolve() if keep is not None else None

    removed = 0
    warnings: list[str] = []
    try:
        candidates = sorted(log_dir.glob(LOG_GLOB))
    except OSError:
        return 0, []

    for path in candidates:
        if not path.is_file():
            continue
        if keep_resolved is not None and path.resolve() == keep_resolved:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
        except OSError as exc:
            warnings.append(f"오래된 로그 {path} 를 지우지 못했다: {exc}")
            continue
        removed += 1

    return removed, warnings


def tail_lines(path: Path, *, lines: int = 200, max_bytes: int = 65536) -> list[str]:
    """파일 끝에서 최대 max_bytes 를 읽어 마지막 lines 줄을 돌려준다.

    로그 파일은 커질 수 있으므로 전체를 읽지 않는다. 잘린 첫 줄은 반쪽이라
    버린다.
    """
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            chunk = handle.read()
    except OSError:
        return []

    text = chunk.decode("utf-8", errors="replace")
    if size > max_bytes:
        _, _, text = text.partition("\n")
    return text.splitlines()[-lines:]
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_logpaths.py -q`
Expected: PASS (24 tests)

- [ ] **Step 5: 커밋한다**

```bash
git add src/mcp_test_server/logpaths.py tests/test_logpaths.py
git commit -m "feat(log): 로그 경로 해석과 72시간 보관 청소를 추가한다"
```

---

### Task 2: `logsetup.py` — 포매터, 날짜 경계 핸들러, 로깅 구성

**Files:**
- Create: `src/mcp_test_server/logsetup.py`
- Test: `tests/test_logsetup.py`

**Interfaces:**
- Consumes: `logpaths.log_file_name`, `logpaths.DEFAULT_LOG_DIR`
- Produces:
  - `ClockFormatter(clock)` — `logging.Formatter` 하위 클래스
  - `DailyFileHandler(log_dir: Path, port: int, clock)` — `logging.FileHandler` 하위 클래스, `current_path` 프로퍼티
  - `LoggingHandle` — `log_dir: Path | None`, `log_file` 프로퍼티, `broadcaster: LogBroadcaster`, `shutdown()`
  - `configure_logging(*, log_dir: Path, port: int, clock, broadcaster) -> LoggingHandle`

`configure_logging`은 **루트 로거**에 핸들러를 붙인다. `mcp_test_server` 로거에만 붙이면 uvicorn 로그가 잡히지 않는다 — `uvicorn.error`는 루트로 전파되지 `mcp_test_server`로 가지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_logsetup.py`:

```python
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


def test_exception_text_is_appended(caplog: object) -> None:
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


def test_configure_logging_attaches_to_the_root_logger_so_uvicorn_is_caught(
    tmp_path: Path,
) -> None:
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_logsetup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.logsetup'`

- [ ] **Step 3: 구현한다**

`src/mcp_test_server/logsetup.py`:

```python
"""로깅 구성 — 형식, 날짜 경계, 핸들러 부착.

핸들러는 mcp_test_server 로거가 아니라 **루트 로거**에 붙인다. uvicorn 의
로거는 루트로 전파되지 우리 로거로 가지 않으므로, 루트에 붙여야 서버가
내는 모든 줄이 한 파일에 모인다.

configure_logging() 은 __main__.main() 에서만 부른다. build_stack() 이
부르면 테스트가 돌 때마다 전역 로깅 상태가 오염된다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
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

    def _path_for(self, day: object) -> Path:
        return self._log_dir / log_file_name(self._port, day)  # type: ignore[arg-type]

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
    ) -> None:
        self.log_dir = log_dir
        self.broadcaster = broadcaster
        self._file_handler = file_handler
        self._added = added

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
            file=__import__("sys").stderr,
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

    return LoggingHandle(resolved_dir, file_handler, broadcaster, added)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_logsetup.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: 되돌려 실제로 실패하는지 확인한다**

`DailyFileHandler.emit`에서 `today = self._clock().date()`를 `today = self._day`로 바꾸고 `uv run pytest tests/test_logsetup.py -q`를 돌린다.
Expected: `test_handler_switches_file_when_the_injected_clock_crosses_midnight` FAIL. 확인한 뒤 되돌린다.

- [ ] **Step 6: 커밋한다**

```bash
git add src/mcp_test_server/logsetup.py tests/test_logsetup.py
git commit -m "feat(log): 주입된 시계로 날짜를 가르는 파일 핸들러와 포매터를 추가한다"
```

---

### Task 3: `logstream.py` — SSE 브로드캐스터

**Files:**
- Create: `src/mcp_test_server/logstream.py`
- Test: `tests/test_logstream.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `LogBroadcaster(max_queue: int = 1000)` — `bind_loop(loop)`, `subscribe() -> asyncio.Queue[str]`, `unsubscribe(queue)`, `publish(line)`, `subscriber_count` 프로퍼티
  - `BroadcastHandler(broadcaster)` — `logging.Handler` 하위 클래스

Task 2가 `BroadcastHandler`를 import하므로 **이 태스크를 Task 2보다 먼저 구현해도 되고 뒤에 해도 되지만, Task 2의 테스트가 통과하려면 이 파일이 있어야 한다.** 순서대로 실행한다면 Task 2 단계에서 이 모듈을 최소 형태로 먼저 만들게 되므로, 이 태스크는 그 파일을 완성하고 테스트를 붙이는 일이 된다. Task 2를 시작하기 전에 이 Task 3을 먼저 끝내는 편이 깔끔하다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_logstream.py`:

```python
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
    """기동 로그와 크래시 로그가 여기 걸린다. 해피 패스 SSE 테스트로는 못 잡는다."""
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_logstream.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.logstream'`

- [ ] **Step 3: 구현한다**

`src/mcp_test_server/logstream.py`:

```python
"""로그 줄을 SSE 구독자에게 fan-out 한다.

파일을 다시 읽지 않는다. 로깅 핸들러에서 바로 밀기 때문에 파일 회전은
스트림과 무관하고, 파일 로깅이 꺼져 있어도 스트림은 동작한다.
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_logstream.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: 되돌려 실제로 실패하는지 확인한다**

`publish`의 `if loop is None or loop.is_closed(): return`을 지우고 `uv run pytest tests/test_logstream.py -q`를 돌린다.
Expected: `test_publish_without_a_loop_does_not_raise`가 `AttributeError`로 FAIL. 확인한 뒤 되돌린다.

- [ ] **Step 6: 커밋한다**

```bash
git add src/mcp_test_server/logstream.py tests/test_logstream.py
git commit -m "feat(log): SSE 구독자에게 로그를 fan-out 하는 브로드캐스터를 추가한다"
```

---

### Task 4: 접근 로그 미들웨어와 토큰 마스킹

**Files:**
- Create: `src/mcp_test_server/access.py`
- Modify: `src/mcp_test_server/auth.py`
- Test: `tests/test_access.py`, `tests/test_auth.py` (추가)

**Interfaces:**
- Consumes: 없음 (`auth.py`의 기존 `AuthMiddleware`와 스코프 키로만 결합)
- Produces:
  - `auth.mask_secret(value: str) -> str`
  - `auth.AUTH_SCOPE_KEY: str` — `"mcp_test_auth"`
  - `access.AccessLogMiddleware(app: ASGIApp)`

**`scope["mcp_test_auth"]`의 소유권:** 스키마는 이 태스크가 정의한다. `auth.py`가 쓰고 `access.py`가 읽는다. 한쪽을 바꾸는 것은 곧 양쪽을 바꾸는 것이다.

```python
{"instance": str | None, "subject": str | None, "reason": str | None}
```

`reason`은 `"blank-token"`, `"blocked"`, 또는 `None`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_access.py`:

```python
"""접근 로그 미들웨어. 거부된 요청도 남는지가 핵심이다."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_test_server.access import AccessLogMiddleware
from mcp_test_server.auth import AuthMiddleware
from mcp_test_server.registry import Registry


def clock() -> datetime:
    return datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


async def ok(request: object) -> JSONResponse:
    return JSONResponse({"ok": True})


def build(registry: Registry) -> AccessLogMiddleware:
    inner = Starlette(routes=[Route("/mcp", ok, methods=["POST", "GET"])])
    return AccessLogMiddleware(AuthMiddleware(inner, registry=registry, clock=clock))


def http_lines(caplog: object) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.http"]


async def test_rejected_request_is_logged_with_its_reason(caplog) -> None:
    """AuthMiddleware 가 조기 return 하므로, 순진한 구현에서는 이 줄이 아예 생기지 않는다."""
    registry = Registry(stale_after=300.0)
    caplog.set_level(logging.INFO, logger="mcp_test_server.http")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build(registry)), base_url="http://t"
    ) as client:
        response = await client.post("/mcp", headers={"Authorization": "Bearer   "})

    assert response.status_code == 401
    lines = http_lines(caplog)
    assert len(lines) == 1
    assert "401" in lines[0]
    assert "reason=blank-token" in lines[0]


async def test_rejected_request_is_logged_at_warning(caplog) -> None:
    registry = Registry(stale_after=300.0)
    caplog.set_level(logging.INFO, logger="mcp_test_server.http")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build(registry)), base_url="http://t"
    ) as client:
        await client.post("/mcp", headers={"Authorization": "Bearer   "})

    record = [r for r in caplog.records if r.name == "mcp_test_server.http"][0]
    assert record.levelno == logging.WARNING


async def test_blocked_request_is_logged_with_reason_blocked(caplog) -> None:
    registry = Registry(stale_after=300.0)
    registry.touch(
        instance_id="i1", subject="alice", project="/p", label="l",
        mcp_session_id=None, now=clock(),
    )
    registry.block("i1")
    caplog.set_level(logging.INFO, logger="mcp_test_server.http")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build(registry)), base_url="http://t"
    ) as client:
        response = await client.post(
            "/mcp", headers={"Authorization": "Bearer alice", "X-Client-Instance": "i1"}
        )

    assert response.status_code == 403
    assert "reason=blocked" in http_lines(caplog)[0]


async def test_successful_request_logs_once_at_info_with_masked_subject(caplog) -> None:
    registry = Registry(stale_after=300.0)
    caplog.set_level(logging.INFO, logger="mcp_test_server.http")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build(registry)), base_url="http://t"
    ) as client:
        await client.post(
            "/mcp", headers={"Authorization": "Bearer alice", "X-Client-Instance": "i1"}
        )

    lines = http_lines(caplog)
    assert len(lines) == 1                     # 401 경로처럼 두 줄이 나오면 안 된다
    assert "POST /mcp 200" in lines[0]
    assert "dur_ms=" in lines[0]
    assert "instance=i1" in lines[0]
    assert "alice" not in lines[0]             # 평문 토큰이 새면 안 된다
    assert "sha256:" in lines[0]


async def test_lifespan_scope_passes_through_untouched() -> None:
    """이 규칙을 어기면 인수 테스트 전부가 멈춘다."""
    seen: list[str] = []

    async def inner(scope, receive, send) -> None:
        seen.append(scope["type"])

    await AccessLogMiddleware(inner)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]
```

`tests/test_auth.py`에 덧붙일 것:

```python
def test_mask_secret_is_stable_and_hides_the_token() -> None:
    from mcp_test_server.auth import mask_secret

    assert mask_secret("alice") == "al…(sha256:2bd806c9)"
    assert mask_secret("alice") == mask_secret("alice")
    assert mask_secret("alice") != mask_secret("bob")


def test_mask_secret_handles_short_and_empty_values() -> None:
    from mcp_test_server.auth import mask_secret

    assert mask_secret("") == "(empty)"
    assert mask_secret("a") == "a…(sha256:ca978112)"


async def test_auth_middleware_records_its_decision_in_the_scope() -> None:
    """access.py 가 읽는 계약이다. 한쪽을 바꾸면 양쪽을 바꿔야 한다."""
    from mcp_test_server.auth import AUTH_SCOPE_KEY, AuthMiddleware

    captured: dict[str, object] = {}

    async def inner(scope, receive, send) -> None:
        captured.update(scope.get(AUTH_SCOPE_KEY) or {})

    registry = Registry(stale_after=300.0)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (b"authorization", b"Bearer alice"),
            (b"x-client-instance", b"i1"),
        ],
    }
    await AuthMiddleware(inner, registry=registry, clock=lambda: T0)(scope, None, None)

    assert captured == {"instance": "i1", "subject": "alice", "reason": None}


async def test_new_connection_is_logged_once_with_a_masked_subject(caplog) -> None:
    import logging

    from mcp_test_server.auth import AuthMiddleware

    caplog.set_level(logging.INFO, logger="mcp_test_server.registry")
    registry = Registry(stale_after=300.0)

    async def inner(scope, receive, send) -> None:
        return None

    middleware = AuthMiddleware(inner, registry=registry, clock=lambda: T0)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (b"authorization", b"Bearer alice"),
            (b"x-client-instance", b"i1"),
        ],
    }
    await middleware(dict(scope), None, None)
    await middleware(dict(scope), None, None)      # 두 번째는 새 연결이 아니다

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.registry"]
    assert len(lines) == 1
    assert "instance=i1" in lines[0]
    assert "alice" not in lines[0]
    assert "sha256:" in lines[0]
```

> `T0`은 `tests/test_auth.py:12`에 이미 있는 `datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)`이다.

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_access.py tests/test_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.access'`

- [ ] **Step 3: `auth.py`를 고친다**

`auth.py` 상단 import에 `hashlib`을 더하고, `UNKNOWN_INSTANCE` 옆에 상수를 추가한다.

```python
import hashlib

UNKNOWN_INSTANCE = "unknown"
_BEARER_PREFIX = "bearer "

# access.py 가 읽는 스코프 키. 스키마는 이 모듈이 정의한다.
#   {"instance": str | None, "subject": str | None, "reason": str | None}
AUTH_SCOPE_KEY = "mcp_test_auth"
```

`read_identity` 아래에 추가한다.

```python
def mask_secret(value: str) -> str:
    """토큰을 로그에 적을 수 있는 형태로 바꾼다.

    같은 입력은 항상 같은 출력이므로 "이 두 요청은 같은 사람"을 추적할 수
    있다. 앞 두 글자를 남기는 것은 별명을 쓴 경우 사람이 알아보게 하려는
    것이다.

    마스킹은 기록 시점에 한다. 포매터가 정규식으로 훑는 방식은 새 필드가
    생길 때마다 조용히 샌다.
    """
    if not value:
        return "(empty)"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[:2]}…(sha256:{digest})"
```

`AuthMiddleware.__call__`을 고쳐 판단 결과를 스코프에 남긴다. 세 지점에 한 줄씩 들어간다.

```python
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        identity = read_identity(Headers(scope=scope))
        if identity is None:
            scope[AUTH_SCOPE_KEY] = {
                "instance": None,
                "subject": None,
                "reason": "blank-token",
            }
            await self._reject(
                scope,
                receive,
                send,
                status=401,
                detail="Authorization 헤더에 비어 있지 않은 Bearer 토큰이 필요하다",
                headers={"WWW-Authenticate": "Bearer"},
            )
            return

        if self.registry.is_blocked(identity.instance_id):
            scope[AUTH_SCOPE_KEY] = {
                "instance": identity.instance_id,
                "subject": identity.subject,
                "reason": "blocked",
            }
            await self._reject(
                scope,
                receive,
                send,
                status=403,
                detail=f"연결 {identity.instance_id} 이(가) 관리 화면에서 차단되었다",
            )
            return

        scope[AUTH_SCOPE_KEY] = {
            "instance": identity.instance_id,
            "subject": identity.subject,
            "reason": None,
        }

        if self.registry.get(identity.instance_id) is None:
            # 처음 보는 연결이다. touch 하면 레코드가 생겨 버리므로 그 전에 본다.
            registry_logger.info(
                "connected instance=%s subject=%s label=%s",
                identity.instance_id,
                mask_secret(identity.subject),
                identity.label,
            )

        if scope["method"] == "DELETE":
            ...
```

`DELETE` 분기 아래는 손대지 않는다. `auth.py` 상단에 로거를 더한다.

```python
import logging

registry_logger = logging.getLogger("mcp_test_server.registry")
```

스펙 §2.1이 요구하는 `registry` 로거는 세 곳에서 나온다 — 새 연결(여기), 차단/해제(Task 7의 `admin.py`), purge 결과(Task 6의 `_purge_loop`). **stale 전이는 남기지 않는다.** stale은 읽는 시점에 `last_seen`으로 계산되는 파생값이지 어딘가에서 일어나는 사건이 아니다. 남기려면 상태 변화를 감시하는 폴러를 새로 만들어야 하고, 그것은 이 기능이 필요로 하지 않는다.

- [ ] **Step 4: `access.py`를 만든다**

```python
"""접근 로그 미들웨어.

AuthMiddleware **바깥**에 선다. 401/403 분기는 응답을 보내고 즉시 return
하므로, 그 안쪽에서 상태 코드를 가로채면 거부된 요청이 로그에 아예 남지
않는다 — 그런데 이 서버에서 가장 보고 싶은 줄이 그것이다. 바깥에 서면
거부 응답도 우리가 넘겨준 send 래퍼를 지나간다.

두 앱(MCP, 관리)에 모두 붙여 같은 형식의 접근 로그를 갖게 한다.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import AUTH_SCOPE_KEY, mask_secret

logger = logging.getLogger("mcp_test_server.http")


class AccessLogMiddleware:
    """요청 하나당 로그 한 줄. 거부된 요청도 포함한다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.monotonic()
        logged = False

        async def wrapped(message: dict) -> None:
            nonlocal logged
            # 응답 완료가 아니라 **첫 응답 시작**에서 남긴다. 이 서버는
            # 스트리밍 응답을 다루므로, 완료 시점에 남기면 /api/logs/stream
            # 같은 장수 연결은 브라우저 탭이 닫힐 때까지 접근 로그가 아예
            # 남지 않는다. 그 대신 SSE 연결은 열리는 순간 dur_ms 가 0에
            # 가까운 줄 하나를 남기고 갱신되지 않는다. 의도한 동작이다.
            if message["type"] == "http.response.start" and not logged:
                logged = True
                self._log(scope, message["status"], (time.monotonic() - started) * 1000.0)
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            if not logged:
                # 응답을 한 번도 시작하지 못하고 터진 경우다. 상태는 없지만
                # 요청이 있었다는 사실은 남겨야 한다.
                self._log(scope, 0, (time.monotonic() - started) * 1000.0)

    def _log(self, scope: Scope, status: int, duration_ms: float) -> None:
        info = scope.get(AUTH_SCOPE_KEY) or {}
        parts = [
            scope.get("method", "?"),
            scope.get("path", "?"),
            str(status),
            f"dur_ms={duration_ms:.0f}",
        ]
        if info.get("instance"):
            parts.append(f"instance={info['instance']}")
        if info.get("subject"):
            parts.append(f"subject={mask_secret(str(info['subject']))}")
        if info.get("reason"):
            parts.append(f"reason={info['reason']}")

        level = logging.WARNING if status >= 400 else logging.INFO
        logger.log(level, " ".join(parts))
```

`AccessLogMiddleware`가 `AuthMiddleware` 바깥에 있으므로, `AuthMiddleware`가 조기 `return`으로 보내는 401/403도 위 `wrapped`를 지나간다. **이것이 이 태스크의 핵심이다** — 안쪽에 두면 거부된 요청이 로그에 아예 남지 않는다. 계획 작성 중 실제로 돌려 확인했다.

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_access.py tests/test_auth.py -q`
Expected: PASS

- [ ] **Step 6: 되돌려 실제로 실패하는지 확인한다**

`access.py`의 `AccessLogMiddleware`를 `AuthMiddleware` **안쪽**에 두도록 `build()` 헬퍼를 `AuthMiddleware(AccessLogMiddleware(inner), ...)`로 바꾸고 돌린다.
Expected: `test_rejected_request_is_logged_with_its_reason`가 `len(lines) == 1`에서 FAIL(0줄). 확인한 뒤 되돌린다.

- [ ] **Step 7: 커밋한다**

```bash
git add src/mcp_test_server/access.py src/mcp_test_server/auth.py tests/test_access.py tests/test_auth.py
git commit -m "feat(log): 거부된 요청까지 남기는 접근 로그와 토큰 마스킹을 추가한다"
```

---

### Task 5: 도구 호출 로그

**Files:**
- Modify: `src/mcp_test_server/mcp_server.py`
- Test: `tests/test_mcp_server.py` (추가)

**Interfaces:**
- Consumes: `auth.UNKNOWN_INSTANCE`, `auth.read_identity` (이미 쓰고 있다)
- Produces: 없음 (내부 데코레이터)

**검증됨:** `functools.wraps`로 감싼 함수를 `@mcp.tool()`에 넘겨도 FastMCP는 스키마를 올바로 만들고 `ctx: Context`를 스키마에서 제외한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_mcp_server.py`에 덧붙인다.

```python
async def test_tool_call_is_logged_with_name_and_instance(caplog) -> None:
    import logging

    from mcp_test_server.mcp_server import build_mcp

    caplog.set_level(logging.INFO, logger="mcp_test_server.call")
    registry = Registry(stale_after=300.0)
    mcp = build_mcp(registry, started_at=T0, clock=lambda: T0)

    await mcp.call_tool("echo", {"text": "안녕"})

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.call"]
    assert len(lines) == 1
    assert "tool=echo" in lines[0]
    assert "dur_ms=" in lines[0]
    assert "ok" in lines[0]


async def test_tool_failure_is_logged_as_error(caplog) -> None:
    import logging

    import pytest

    from mcp_test_server.mcp_server import build_mcp

    caplog.set_level(logging.INFO, logger="mcp_test_server.call")
    registry = Registry(stale_after=300.0)
    mcp = build_mcp(registry, started_at=T0, clock=lambda: T0)

    with pytest.raises(Exception):
        await mcp.call_tool("echo", {})        # text 가 없다

    records = [r for r in caplog.records if r.name == "mcp_test_server.call"]
    assert records and records[0].levelno >= logging.WARNING


async def test_tool_schemas_are_unchanged_by_the_logging_decorator() -> None:
    """데코레이터가 시그니처를 가리면 도구가 조용히 망가진다."""
    from mcp_test_server.mcp_server import build_mcp

    mcp = build_mcp(Registry(stale_after=300.0), started_at=T0, clock=lambda: T0)
    by_name = {t.name: t for t in await mcp.list_tools()}

    assert set(by_name) == {"ping", "echo", "whoami", "sessions"}
    assert sorted(by_name["echo"].inputSchema.get("properties", {})) == ["text"]
    assert by_name["echo"].inputSchema.get("required") == ["text"]
    assert by_name["ping"].inputSchema.get("properties", {}) == {}
    assert by_name["whoami"].inputSchema.get("properties", {}) == {}
```

> `T0`는 `tests/test_mcp_server.py:7`에 이미 있다. `Registry`는 `tests/test_admin.py`처럼 인자 없이 `Registry()`로도 만들 수 있다.

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_mcp_server.py -q`
Expected: 새 테스트 3개 중 로그를 보는 2개가 FAIL (`assert len(lines) == 1`에서 0줄)

- [ ] **Step 3: 구현한다**

`mcp_server.py` 상단에 추가한다.

```python
import functools
import logging
import time

logger = logging.getLogger("mcp_test_server.call")
```

`_instance_id_of` 아래에 데코레이터를 만든다.

```python
def _logged(fn):
    """도구 호출을 한 줄 남긴다.

    functools.wraps 가 __wrapped__ 를 남기므로 inspect.signature 가 원래
    시그니처를 따라간다. FastMCP 는 그것으로 스키마를 만들므로 도구의
    입력 스키마가 바뀌지 않는다 — ctx: Context 는 그대로 제외된다.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.monotonic()
        instance = UNKNOWN_INSTANCE
        ctx = kwargs.get("ctx")
        if ctx is not None:
            instance = _instance_id_of(ctx)
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            logger.warning(
                "tool=%s instance=%s dur_ms=%.0f error=%s",
                fn.__name__,
                instance,
                elapsed,
                type(exc).__name__,
            )
            raise
        elapsed = (time.monotonic() - started) * 1000.0
        logger.info(
            "tool=%s instance=%s dur_ms=%.0f ok", fn.__name__, instance, elapsed
        )
        return result

    return wrapper
```

네 도구 각각에 `@mcp.tool()` **아래**로 `@_logged`를 붙인다. 순서가 중요하다 — `mcp.tool()`이 바깥이어야 감싼 함수를 등록한다.

```python
    @mcp.tool()
    @_logged
    def ping() -> dict[str, object]:
        ...

    @mcp.tool()
    @_logged
    def echo(text: str) -> str:
        ...

    @mcp.tool()
    @_logged
    def whoami(ctx: Context) -> dict[str, object]:
        ...

    @mcp.tool()
    @_logged
    def sessions() -> dict[str, object]:
        ...
```

`ping`, `echo`, `sessions`는 `ctx`를 받지 않으므로 `instance`가 `unknown`으로 남는다. 그 요청의 연결 ID는 같은 시각의 `http` 줄에 있으므로 상관없다. 도구에 `ctx`를 억지로 붙이면 스키마와 서명이 넓어지기만 한다.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_mcp_server.py -q`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/mcp_test_server/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(log): 도구 호출 이름과 소요 시간을 남긴다"
```

---

### Task 6: 배선과 크래시 경로

**Files:**
- Modify: `src/mcp_test_server/app.py`, `src/mcp_test_server/__main__.py`
- Test: `tests/test_app.py` (추가)

**Interfaces:**
- Consumes: `logpaths.resolve_log_dir`, `logpaths.purge_logs`, `logsetup.configure_logging`, `logsetup.LoggingHandle`, `logstream.LogBroadcaster`, `access.AccessLogMiddleware`
- Produces:
  - `app.build_stack(..., broadcaster: LogBroadcaster | None = None, log_file: Callable[[], Path | None] = lambda: None)` — 기존 인자 뒤에 키워드 두 개
  - `app.serve(..., handle: LoggingHandle | None = None)`
  - `__main__.parse_args`에 `--log-dir`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_app.py`에 덧붙인다.

```python
def test_log_dir_flag_is_parsed() -> None:
    from mcp_test_server.__main__ import parse_args

    assert parse_args(["--log-dir", "/tmp/x"]).log_dir == "/tmp/x"
    assert parse_args([]).log_dir is None


def test_both_apps_are_wrapped_in_the_access_log_middleware() -> None:
    """관리 앱만 빠지면 접근 로그가 반쪽이 된다."""
    from mcp_test_server.access import AccessLogMiddleware
    from mcp_test_server.app import build_stack

    mcp_app, admin_app, _registry = build_stack(
        host="127.0.0.1", port=1, admin_port=2, stale_after=300.0
    )
    assert isinstance(mcp_app, AccessLogMiddleware)
    assert isinstance(admin_app, AccessLogMiddleware)


async def test_purge_loop_cleans_log_files(tmp_path, monkeypatch) -> None:
    """청소가 실제로 _purge_loop 를 타는지 본다.

    여기서 purge_logs 를 직접 부르고 결과만 확인하면 루프가 죽어 있어도
    통과한다. 주기를 0으로 줄여 루프 자신이 지우게 한다.
    """
    import asyncio
    import os
    from datetime import timedelta

    from mcp_test_server import app as app_module
    from mcp_test_server.registry import Registry

    now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
    old = tmp_path / "mcp-test-server.8765.2026-07-20.log"
    old.write_text("x", encoding="utf-8")
    stamp = (now - timedelta(hours=200)).timestamp()
    os.utime(old, (stamp, stamp))

    monkeypatch.setattr(app_module, "_PURGE_INTERVAL_SECONDS", 0.0)
    task = asyncio.create_task(
        app_module._purge_loop(
            Registry(stale_after=300.0), lambda: now, tmp_path, lambda: None
        )
    )
    try:
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not old.exists():
                break
    finally:
        task.cancel()

    assert not old.exists()


async def test_serve_binds_the_broadcaster_to_the_running_loop() -> None:
    """루프를 묶지 않으면 SSE 로 단 한 줄도 나가지 않는다."""
    import asyncio

    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()
    broadcaster.publish("확인")
    await asyncio.sleep(0)
    assert await asyncio.wait_for(queue.get(), timeout=1.0) == "확인"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_app.py -q`
Expected: FAIL — `--log-dir` 미지원, `AccessLogMiddleware` 미적용, `_purge_loop` 인자 개수 불일치

- [ ] **Step 3: `app.py`를 고친다**

import에 추가한다.

```python
from pathlib import Path

from .access import AccessLogMiddleware
from .logpaths import purge_logs
from .logstream import LogBroadcaster
```

`build_stack`을 고친다. 반환 타입의 두 번째 요소가 `Starlette`에서 `ASGIApp`으로 바뀐다.

```python
def build_stack(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
    clock: Callable[[], datetime] = _utcnow,
    broadcaster: LogBroadcaster | None = None,
    log_file: Callable[[], Path | None] = lambda: None,
) -> tuple[ASGIApp, ASGIApp, Registry]:
    """MCP 앱, 관리 앱, 그리고 둘이 공유하는 레지스트리를 만든다.

    admin_port는 지금 쓰지 않는다. 나중에 관리 앱 쪽에 인증이나 Origin
    검사를 붙일 때 자기 포트를 알아야 하므로 자리를 비워 둔다.

    두 앱 모두 AccessLogMiddleware 로 감싼다. 관리 앱만 빼면 접근 로그가
    반쪽이 되고, uvicorn 의 access log 를 껐으므로 그쪽 요청은 어디에도
    남지 않는다.
    """
    started_at = clock()
    registry = Registry(stale_after=stale_after)

    mcp = build_mcp(registry, started_at=started_at, clock=clock)
    mcp_app = AccessLogMiddleware(
        AuthMiddleware(mcp.streamable_http_app(), registry=registry, clock=clock)
    )

    admin_app = AccessLogMiddleware(
        build_admin_app(
            registry,
            started_at=started_at,
            clock=clock,
            mcp_endpoint=f"http://{endpoint_host(host)}:{port}/mcp",
            broadcaster=broadcaster,
            log_file=log_file,
        )
    )
    return mcp_app, admin_app, registry
```

`build_servers`의 두 `uvicorn.Config`에 `log_config=None, access_log=False`를 더한다. 타입 힌트의 `admin_app: Starlette`도 `ASGIApp`으로 바꾼다.

```python
def build_servers(
    mcp_app: ASGIApp,
    admin_app: ASGIApp,
    *,
    host: str,
    port: int,
    admin_port: int,
) -> tuple[uvicorn.Server, uvicorn.Server]:
    """두 리스너의 uvicorn 설정을 만든다. 아직 아무것도 바인딩하지 않는다.

    serve() 안에 인라인으로 두면 "관리 리스너만은 ADMIN_HOST에 고정된다"는
    성질을 테스트가 확인할 방법이 없다. 바인딩 없이 설정만 돌려주는 함수로
    떼어 내 그 성질을 검증 가능하게 만든다.

    log_config=None 은 uvicorn 이 자기 핸들러를 설치하지 못하게 한다.
    그러면 uvicorn.error 가 루트로 전파되어 우리 파일에 함께 쌓인다.
    access_log=False 인 이유는 AccessLogMiddleware 가 양쪽 앱에 대해
    같은 형식으로 남기기 때문이다.
    """
    mcp_server = uvicorn.Server(
        uvicorn.Config(
            mcp_app,
            host=host,
            port=port,
            log_level="info",
            log_config=None,
            access_log=False,
        )
    )
    admin_server = uvicorn.Server(
        uvicorn.Config(
            admin_app,
            host=ADMIN_HOST,
            port=admin_port,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
    )
    return mcp_server, admin_server
```

`_purge_loop`에 로그 청소를 얹는다.

```python
async def _purge_loop(
    registry: Registry,
    clock: Callable[[], datetime],
    log_dir: Path | None,
    log_file: Callable[[], Path | None],
) -> None:
    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        now = clock()
        registry.purge(now)
        if log_dir is not None:
            removed, warnings = purge_logs(log_dir, now, keep=log_file())
            if removed:
                registry_logger.info("오래된 로그 %d개를 지웠다", removed)
            for warning in warnings:
                logger.warning("%s", warning)
```

`app.py` 상단에 `registry_logger = logging.getLogger("mcp_test_server.registry")`를 더한다.

`serve()`를 고친다.

```python
async def serve(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
    handle: LoggingHandle | None = None,
) -> None:
    """두 리스너를 동시에 띄운다. 하나가 죽으면 함께 끝난다."""
    ensure_port_free(host, port)
    ensure_port_free(ADMIN_HOST, admin_port)

    warning = exposure_warning(host)
    if warning is not None:
        print(warning, file=sys.stderr)
        logger.warning("%s", warning)

    broadcaster = handle.broadcaster if handle else None
    log_dir = handle.log_dir if handle else None
    log_file: Callable[[], Path | None] = (
        (lambda: handle.log_file) if handle else (lambda: None)
    )

    loop = asyncio.get_running_loop()
    if broadcaster is not None:
        broadcaster.bind_loop(loop)
    loop.set_exception_handler(_loop_exception_handler)

    mcp_app, admin_app, registry = build_stack(
        host=host,
        port=port,
        admin_port=admin_port,
        stale_after=stale_after,
        broadcaster=broadcaster,
        log_file=log_file,
    )
    mcp_server, admin_server = build_servers(
        mcp_app, admin_app, host=host, port=port, admin_port=admin_port
    )

    print(f"MCP    http://{host}:{port}/mcp")
    print(f"관리   http://{ADMIN_HOST}:{admin_port}/")
    if log_dir is not None:
        print(f"로그   {log_file()}")
        # 기동 직후 한 번 청소한다. _purge_loop 는 10분 뒤에야 처음 돈다.
        _, warnings = purge_logs(log_dir, _utcnow(), keep=log_file())
        for message in warnings:
            logger.warning("%s", message)
    logger.info("서버 기동 MCP=%s:%s 관리=%s:%s", host, port, ADMIN_HOST, admin_port)

    purge = asyncio.create_task(_purge_loop(registry, _utcnow, log_dir, log_file))
    try:
        await asyncio.gather(mcp_server.serve(), admin_server.serve())
    finally:
        purge.cancel()
        logger.info("서버 종료")
```

파일 상단에 로거와 루프 예외 핸들러를 더한다.

```python
import logging

logger = logging.getLogger("mcp_test_server.app")


def _loop_exception_handler(
    loop: asyncio.AbstractEventLoop, context: dict[str, object]
) -> None:
    """태스크 안에서 난 예외는 main() 까지 오지 않는다.

    purge 태스크와 uvicorn 의 커넥션별 태스크가 여기 걸린다. 이걸 걸지
    않으면 그 예외들은 asyncio 의 기본 핸들러가 stderr 로만 흘려보내고,
    stderr 는 아무 데도 가지 않는다.
    """
    exc = context.get("exception")
    message = context.get("message", "이벤트 루프에서 처리되지 않은 예외")
    if isinstance(exc, BaseException):
        logger.error("%s", message, exc_info=exc)
    else:
        logger.error("%s", message)
```

- [ ] **Step 4: `__main__.py`를 고친다**

```python
"""CLI 진입점."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import sys

from .app import DEFAULTS, PortInUse, serve
from .logpaths import resolve_log_dir
from .logsetup import configure_logging
from .logstream import LogBroadcaster
```

`parse_args`에 플래그를 더한다.

```python
    parser.add_argument(
        "--log-dir",
        default=None,
        help=(
            "로그 파일을 남길 디렉토리. 지정하지 않으면 $MCP_TEST_LOG_DIR, "
            "그다음 플러그인 설정, 그다음 ~/.mcp-test-server/logs 를 쓴다"
        ),
    )
```

`main`을 고친다.

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    log_dir, warnings = resolve_log_dir(
        flag=args.log_dir, env=os.environ.get("MCP_TEST_LOG_DIR")
    )
    handle = configure_logging(
        log_dir=log_dir,
        port=args.port,
        clock=_utcnow,
        broadcaster=LogBroadcaster(),
    )
    # 로깅이 준비된 뒤에 남긴다. 경로를 정하는 동안에는 남길 곳이 없었다.
    for message in warnings:
        logging.getLogger("mcp_test_server.app").warning("%s", message)
    atexit.register(logging.shutdown)

    try:
        asyncio.run(
            serve(
                host=args.host,
                port=args.port,
                admin_port=args.admin_port,
                stale_after=args.stale_after,
                handle=handle,
            )
        )
    except PortInUse as exc:
        print(f"기동 실패: {exc}", file=sys.stderr)
        print("--port 또는 --admin-port 로 다른 포트를 지정하라.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except BaseException:
        # Exception 이 아니라 BaseException 이다. uvicorn 은 바인딩에 실패하면
        # sys.exit(1) 을 부르고 SystemExit 은 BaseException 이다 —
        # app.py 의 ensure_port_free 주석이 그 사실을 기록하고 있다.
        logging.getLogger("mcp_test_server.app").exception("처리되지 않은 예외로 종료한다")
        raise
    finally:
        # atexit 은 인터프리터가 정리를 시작한 뒤에 돈다. 그때 파일 핸들러가
        # 부르는 시계는 모듈 전역을 참조하므로 이미 사라졌을 수 있다.
        # 여기서 명시적으로 비우는 것이 주 경로다.
        logging.shutdown()
    return 0
```

`_utcnow`는 `app.py`에 있으므로 import한다: `from .app import DEFAULTS, PortInUse, _utcnow, serve`.

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `uv run pytest -q`
Expected: 기존 78개를 포함해 전부 PASS

기존 `tests/test_acceptance.py`와 `tests/test_app.py`가 `build_stack`을 부르며 반환값을 `Starlette`로 가정하는 곳이 있으면 함께 고친다. `running_server()`는 `mcp_app`만 쓰므로 영향이 없어야 한다.

- [ ] **Step 6: 되돌려 실제로 실패하는지 확인한다**

`__main__.main()`의 `finally: logging.shutdown()`을 지우고 Task 8의 크래시 인수 테스트를 돌린다 — 이 시점에는 아직 없으므로, 대신 `build_stack`의 관리 앱 래핑을 지우고 `test_both_apps_are_wrapped_in_the_access_log_middleware`가 FAIL하는지 확인한다. 확인 뒤 되돌린다.

- [ ] **Step 7: 커밋한다**

```bash
git add src/mcp_test_server/app.py src/mcp_test_server/__main__.py tests/test_app.py
git commit -m "feat(log): 로깅을 배선하고 크래시가 파일에 남도록 한다"
```

---

### Task 7: 관리 화면 — 로그 영역과 SSE

**Files:**
- Modify: `src/mcp_test_server/admin.py`
- Test: `tests/test_admin.py` (추가)

**Interfaces:**
- Consumes: `logpaths.tail_lines`, `logstream.LogBroadcaster`
- Produces: `build_admin_app(..., broadcaster=None, log_file=lambda: None)`; 라우트 `GET /fragments/sessions`, `GET /api/logs/stream`; `/api/status`에 `log_dir`·`log_file`

**`meta refresh` 제거:** `admin.py:44`의 `<meta http-equiv="refresh" content="5">`는 5초마다 페이지 전체를 다시 로드하므로 `EventSource` 연결을 계속 끊는다. 지우고, 세션 표는 JS가 `GET /fragments/sessions`를 5초마다 받아 갈아 끼운다. 표 렌더링은 서버 한 곳에만 있고 브라우저는 HTML을 통째로 바꿔 넣기만 하므로 렌더링이 두 벌로 갈리지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_admin.py`에 덧붙인다.

```python
async def test_page_has_no_meta_refresh_so_sse_survives() -> None:
    """전체 새로고침은 EventSource 연결을 5초마다 끊는다."""
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        page = await client.get("/")
    assert "http-equiv=\"refresh\"" not in page.text


async def test_sessions_fragment_returns_only_the_table() -> None:
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        fragment = await client.get("/fragments/sessions")
    assert fragment.status_code == 200
    assert "abc123" in fragment.text
    assert "<!doctype html>" not in fragment.text.lower()


async def test_status_exposes_the_log_paths(tmp_path) -> None:
    from mcp_test_server.admin import build_admin_app

    log_file = tmp_path / "mcp-test-server.8765.2026-07-25.log"
    log_file.write_text("x", encoding="utf-8")
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        log_file=lambda: log_file,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        body = (await client.get("/api/status")).json()
    assert body["log_file"] == str(log_file)


async def test_status_reports_null_when_file_logging_is_off() -> None:
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        body = (await client.get("/api/status")).json()
    assert body["log_file"] is None


async def test_page_backfills_the_tail_of_the_log_file(tmp_path) -> None:
    from mcp_test_server.admin import build_admin_app

    log_file = tmp_path / "mcp-test-server.8765.2026-07-25.log"
    log_file.write_text("첫 줄\n<script>나쁜것</script>\n", encoding="utf-8")
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        log_file=lambda: log_file,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        page = await client.get("/")

    assert "첫 줄" in page.text
    assert "&lt;script&gt;" in page.text          # 이스케이프됐다
    assert "<script>나쁜것</script>" not in page.text


async def test_stream_emits_published_lines() -> None:
    import asyncio

    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        async with client.stream("GET", "/api/logs/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            await asyncio.sleep(0)
            broadcaster.publish("한 줄")
            chunk = await asyncio.wait_for(
                response.aiter_text().__anext__(), timeout=5.0
            )
    assert "data: 한 줄" in chunk


async def test_stream_splits_multiline_records_into_separate_data_fields() -> None:
    """트레이스백은 여러 줄이다. data: 한 개에 넣으면 SSE 프레이밍이 깨진다."""
    import asyncio

    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        async with client.stream("GET", "/api/logs/stream") as response:
            await asyncio.sleep(0)
            broadcaster.publish("첫 줄\nTraceback\n  두 번째")
            chunk = await asyncio.wait_for(
                response.aiter_text().__anext__(), timeout=5.0
            )
    assert chunk == "data: 첫 줄\ndata: Traceback\ndata:   두 번째\n\n"


async def test_stream_unsubscribes_when_the_client_disconnects() -> None:
    import asyncio

    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        async with client.stream("GET", "/api/logs/stream") as response:
            await asyncio.sleep(0)
            broadcaster.publish("x")
            await asyncio.wait_for(response.aiter_text().__anext__(), timeout=5.0)
    await asyncio.sleep(0.05)
    assert broadcaster.subscriber_count == 0


async def test_gate_blocks_the_log_stream_and_leaks_no_body() -> None:
    """게이트 테스트의 스트림 판. 기존 테스트는 레지스트리 상태만 본다 —
    스트림의 실패 방식은 레지스트리를 건드리지 않고 내용만 새는 것이다."""
    import asyncio

    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    inner = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )
    gate = _ThrowawayGate(inner, token="s3cret")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gate), base_url="http://admin"
    ) as client:
        broadcaster.publish("비밀-한-줄")
        blocked = await client.get("/api/logs/stream")

    assert blocked.status_code == 401
    assert "비밀-한-줄" not in blocked.text
    assert broadcaster.subscriber_count == 0      # 구독조차 만들어지지 않았다
```

> `_ThrowawayGate`, `make_registry`, `build_app`, `T0`는 `tests/test_admin.py`에 이미 있는 것을 쓴다.

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_admin.py -q`
Expected: FAIL — `build_admin_app()`이 `log_file`/`broadcaster` 인자를 모르고, `/fragments/sessions`와 `/api/logs/stream`이 404

- [ ] **Step 3: `admin.py`를 고친다**

import에 더한다.

```python
import asyncio
from pathlib import Path

from starlette.responses import StreamingResponse

from .logpaths import tail_lines
from .logstream import LogBroadcaster
```

`_PAGE`를 고친다. `meta refresh`를 지우고, 세션 영역에 id를 주고, 로그 영역과 JS를 더한다.

```python
_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>MCP 테스트 서버</title>
<style>
body {{ font-family: ui-monospace, monospace; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; }}
.stale {{ color: #888; }}
.blocked {{ background: #fee; }}
.note {{ color: #666; font-size: .9rem; }}
#log {{ background: #111; color: #ddd; padding: .8rem; height: 24rem;
        overflow-y: scroll; white-space: pre-wrap; margin-top: .5rem; }}
</style>
</head>
<body>
<h1>MCP 테스트 서버</h1>
<div id="sessions">{sessions}</div>

<h2>로그</h2>
<p class="note">{log_note}</p>
<pre id="log">{log_backfill}</pre>

<script>
// 세션 표는 폴링, 로그는 SSE. 용도가 다르므로 연결을 따로 둔다.
setInterval(async () => {{
  try {{
    const html = await (await fetch('/fragments/sessions')).text();
    document.getElementById('sessions').innerHTML = html;
  }} catch (e) {{ /* 서버가 잠깐 없을 수 있다. 다음 주기에 다시 시도한다. */ }}
}}, 5000);

const box = document.getElementById('log');
box.scrollTop = box.scrollHeight;
new EventSource('/api/logs/stream').onmessage = (event) => {{
  // 맨 아래를 보고 있을 때만 따라간다. 위로 올려 읽는 중이면 방해하지 않는다.
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent += event.data + '\\n';
  if (atBottom) box.scrollTop = box.scrollHeight;
}};
</script>
</body>
</html>
"""

_SESSIONS = """<p>pid {pid} · uptime {uptime:.0f}s · MCP {endpoint} · 세션 {count}개</p>
<p class="note">차단하면 그 세션은 403을 받고, Claude Code가 headersHelper를
다시 실행해 <b>새 연결 ID로 되살아난다.</b> 레코드가 사라지고 새 줄이
나타나는 것이 정상이다.</p>
<table>
<tr><th>연결 ID</th><th>subject</th><th>project</th><th>label</th>
<th>연결 시각</th><th>마지막 호출</th><th>호출</th><th></th></tr>
{rows}
</table>
"""
```

`_ROW`는 그대로 둔다.

`build_admin_app`의 시그니처와 본문을 고친다.

```python
def build_admin_app(
    registry: Registry,
    started_at: datetime,
    clock: Callable[[], datetime],
    mcp_endpoint: str,
    broadcaster: LogBroadcaster | None = None,
    log_file: Callable[[], Path | None] = lambda: None,
) -> Starlette:
```

`index`를 두 조각으로 나눈다.

```python
    def _sessions_html() -> str:
        now, views = _snapshot()
        rows = "".join(
            _ROW.format(
                classes=" ".join(
                    c for c, on in (("stale", v["stale"]), ("blocked", v["blocked"])) if on
                ),
                instance_id=html.escape(str(v["instance_id"])),
                subject=html.escape(str(v["subject"])),
                project=html.escape(str(v["project"])),
                label=html.escape(str(v["label"])),
                connected_at=html.escape(str(v["connected_at"])),
                last_seen=html.escape(str(v["last_seen"])),
                call_count=v["call_count"],
                action="unblock" if v["blocked"] else "block",
                action_label="차단 해제" if v["blocked"] else "차단",
            )
            for v in views
        )
        return _SESSIONS.format(
            pid=os.getpid(),
            uptime=(now - started_at).total_seconds(),
            endpoint=html.escape(mcp_endpoint),
            count=len(views),
            rows=rows,
        )

    async def sessions_fragment(request: Request) -> HTMLResponse:
        return HTMLResponse(_sessions_html())

    async def index(request: Request) -> HTMLResponse:
        path = log_file()
        if path is None:
            note = "파일 로깅이 꺼져 있다. 아래는 이 연결 이후의 로그만 보여준다."
            backfill = ""
        else:
            note = f"{html.escape(str(path))} · 최근 200줄"
            backfill = html.escape("\n".join(tail_lines(path)))
        return HTMLResponse(
            _PAGE.format(
                sessions=_sessions_html(), log_note=note, log_backfill=backfill
            )
        )
```

`status`에 두 필드를 더한다.

```python
    async def status(request: Request) -> JSONResponse:
        now, views = _snapshot()
        path = log_file()
        return JSONResponse(
            {
                "pid": os.getpid(),
                "uptime_seconds": (now - started_at).total_seconds(),
                "mcp_endpoint": mcp_endpoint,
                "session_count": len(views),
                "sessions": views,
                "log_dir": str(path.parent) if path else None,
                "log_file": str(path) if path else None,
            }
        )
```

SSE 라우트를 더한다.

```python
    async def log_stream(request: Request) -> StreamingResponse | JSONResponse:
        if broadcaster is None:
            return JSONResponse({"error": "로그 스트림이 꺼져 있다"}, status_code=503)

        queue = broadcaster.subscribe()

        async def events():
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # 유휴 연결이 끊기지 않게 하는 주석 하트비트다.
                        yield b": ping\n\n"
                        continue
                    # 트레이스백은 여러 줄이다. 줄마다 data: 를 붙이지 않으면
                    # SSE 프레이밍이 깨진다.
                    payload = "".join(f"data: {part}\n" for part in line.split("\n"))
                    yield (payload + "\n").encode("utf-8")
            finally:
                broadcaster.unsubscribe(queue)

        return StreamingResponse(events(), media_type="text/event-stream")
```

라우트 목록에 두 개를 더한다.

```python
            Route("/fragments/sessions", sessions_fragment),
            Route("/api/logs/stream", log_stream),
```

`_toggle`의 핸들러가 성공했을 때 `registry` 로거에 남긴다 (스펙 §2.1). `admin.py` 상단에 `import logging`과 `registry_logger = logging.getLogger("mcp_test_server.registry")`를 더하고, `if not changed:` 블록 **뒤에** 한 줄을 넣는다.

```python
            registry_logger.info("%s instance=%s", action, instance_id)
```

그리고 이를 확인하는 테스트를 `tests/test_admin.py`에 더한다.

```python
async def test_block_is_recorded_in_the_registry_log(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="mcp_test_server.registry")
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        await client.post("/api/sessions/abc123/block")

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.registry"]
    assert lines == ["block instance=abc123"]


async def test_unknown_instance_is_not_recorded(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="mcp_test_server.registry")
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        response = await client.post("/api/sessions/nope/block")

    assert response.status_code == 404
    assert [r for r in caplog.records if r.name == "mcp_test_server.registry"] == []
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_admin.py -q`
Expected: PASS

- [ ] **Step 5: 되돌려 실제로 실패하는지 확인한다**

`log_stream`의 `payload` 조립을 `payload = f"data: {line}\n"`로 바꾸고 돌린다.
Expected: `test_stream_splits_multiline_records_into_separate_data_fields` FAIL. 확인한 뒤 되돌린다.

- [ ] **Step 6: 커밋한다**

```bash
git add src/mcp_test_server/admin.py tests/test_admin.py
git commit -m "feat(admin): 로그를 SSE로 흘리고 세션 표는 폴링으로 갱신한다"
```

---

### Task 8: 크래시 인수 테스트, 플러그인 설정, 문서

**Files:**
- Modify: `tests/test_acceptance.py`, `plugins/mcp-test/.claude-plugin/plugin.json`, `README.md`
- Test: 위 인수 테스트 파일

**Interfaces:**
- Consumes: Task 1–7의 전부
- Produces: 없음

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_acceptance.py`에 덧붙인다.

```python
async def test_crash_leaves_a_traceback_in_the_log_file(tmp_path) -> None:
    """SIGTERM 으로 죽이는 테스트는 아무것도 증명하지 못한다.

    terminate() 는 SIGTERM 이고 파이썬은 이를 기본적으로 잡지 않는다.
    프로세스는 finally 도 atexit 도 실행하지 않고 즉시 끝나므로, 그렇게
    죽인 뒤 로그를 확인하는 테스트는 통과해도 flush 가 동작한다는 뜻이
    아니다. 대신 진짜 미처리 예외로 죽인다.
    """
    port = free_port()
    child = (
        "import sys\n"
        "import mcp_test_server.app as app\n"
        "import mcp_test_server.__main__ as m\n"
        "async def boom(**kwargs):\n"
        "    raise RuntimeError('deliberate-crash-marker')\n"
        # __main__ 이 from .app import serve 로 이름을 끌어왔으므로 양쪽
        # 모듈 전역을 모두 바꿔야 한다. 한쪽만 바꾸면 패치가 먹지 않고
        # 서버가 정상 기동해 이 테스트가 멈춘다.
        "app.serve = boom\n"
        "m.serve = boom\n"
        "sys.exit(m.main(['--log-dir', sys.argv[1], '--port', sys.argv[2]]))\n"
    )

    proc = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), str(port)],
        capture_output=True,
        timeout=60,
    )

    assert proc.returncode != 0, proc.stderr.decode(errors="replace")

    files = list(tmp_path.glob("mcp-test-server.*.log"))
    assert files, f"로그 파일이 없다. stderr={proc.stderr.decode(errors='replace')}"
    text = files[0].read_text(encoding="utf-8", errors="replace")
    assert "deliberate-crash-marker" in text
    assert "Traceback" in text


async def test_server_starts_even_when_the_log_directory_is_unusable(tmp_path) -> None:
    """로그 디렉토리 때문에 테스트 서버가 뜨지 않는 것은 거꾸로 간 것이다."""
    blocker = tmp_path / "blocked"
    blocker.write_text("파일이라 하위 디렉토리를 만들 수 없다", encoding="utf-8")

    port = free_port()
    admin_port = free_port()
    fd, log_path_str = tempfile.mkstemp(prefix="mcp-test-unusable-", suffix=".log")
    os.close(fd)
    log_path = Path(log_path_str)
    try:
        with open(log_path, "wb") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "mcp_test_server",
                    "--host", "127.0.0.1",
                    "--port", str(port),
                    "--admin-port", str(admin_port),
                    "--log-dir", str(blocker / "logs"),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        try:
            deadline = time.monotonic() + 20.0
            while True:
                if proc.poll() is not None:
                    output = _terminate_and_reap(proc, log_path)
                    pytest.fail(f"서버가 죽었다:\n{output}")
                if await _port_ready("127.0.0.1", port):
                    break
                if time.monotonic() > deadline:
                    output = _terminate_and_reap(proc, log_path)
                    pytest.fail(f"서버가 뜨지 않았다:\n{output}")
                await asyncio.sleep(0.1)

            async with client_for(
                f"http://127.0.0.1:{port}/mcp", "inst-nolog", "nolog"
            ) as session:
                assert payload(await session.call_tool("ping", {}))["pid"] > 0
        finally:
            _terminate_and_reap(proc, log_path)
    finally:
        log_path.unlink(missing_ok=True)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_acceptance.py -q`
Expected: 크래시 테스트가 FAIL — 로그 파일이 없거나 트레이스백이 없다

- [ ] **Step 3: 통과하는지 확인한다**

Task 6까지 끝났다면 이미 통과할 수 있다. 통과하지 않으면 원인은 `__main__.main()`의 `except BaseException` 또는 `finally: logging.shutdown()`이다.

Run: `uv run pytest tests/test_acceptance.py -q`
Expected: PASS

- [ ] **Step 4: 되돌려 실제로 실패하는지 확인한다**

`__main__.main()`의 `finally: logging.shutdown()`을 지우고 크래시 테스트를 돌린다.
Expected: 트레이스백이 파일에 없어 FAIL할 수 있다(버퍼에 남은 채 프로세스 종료). 통과한다면 `atexit`이 대신 일한 것이므로, `atexit.register(logging.shutdown)`도 함께 지워 FAIL을 확인한다. 확인한 뒤 둘 다 되돌린다.

- [ ] **Step 5: 플러그인 설정을 더한다**

`plugins/mcp-test/.claude-plugin/plugin.json`의 `userConfig`에 추가한다.

```json
    "log_dir": {
      "type": "string",
      "title": "서버 로그 디렉토리",
      "description": "비워 두면 ~/.mcp-test-server/logs 를 쓴다. 이 값은 서버가 기동할 때 읽으므로, 바꾸면 서버를 재기동해야 반영된다"
    }
```

`type`은 `directory`가 아니라 `string`이다. `~`로 시작하는 값을 넣을 수 있어야 하고, 아직 없는 디렉토리도 지정할 수 있어야 한다. `default`는 넣지 않는다 — 기본값은 서버가 소유하며, 양쪽에 같은 문자열을 두면 한쪽만 바뀌었을 때 조용히 어긋난다.

`tests/test_plugin_files.py`에 검증을 더한다.

```python
def test_plugin_declares_a_non_sensitive_log_dir_option() -> None:
    config = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["userConfig"]["log_dir"]
    assert config["type"] == "string"
    # 민감으로 표시하면 Keychain 으로 가서 settings.json 에 남지 않고,
    # 서버가 읽을 수 없게 된다.
    assert config.get("sensitive") is not True
    assert "default" not in config
```

- [ ] **Step 6: README를 고친다**

`README.md`에 "로그" 절을 더한다. 다음을 반드시 담는다.

- 기본 위치 `~/.mcp-test-server/logs`, 파일명 `mcp-test-server.<포트>.<날짜>.log`
- 우선순위: `--log-dir` > `$MCP_TEST_LOG_DIR` > 플러그인 설정 `log_dir` > 기본값
- **플러그인 설정을 바꾸면 서버를 재기동해야 반영된다**
- 보관은 72시간, 나이 기준. 기동 시와 10분마다 청소한다
- 관리 화면(`http://127.0.0.1:8766/`)에서 실시간으로 보인다
- **토큰은 마스킹돼 남는다**(`al…(sha256:2bd806c9)`). 다만 프로젝트 경로와 연결 ID는 평문이다
- 로그 디렉토리를 쓸 수 없으면 파일 로깅만 끄고 서버는 뜬다

수동 검증 체크리스트에 두 줄을 더한다.

- [ ] 서버를 띄우고 `~/.mcp-test-server/logs/`에 파일이 생기는지 본다
- [ ] 관리 화면을 열어 둔 채 다른 세션에서 도구를 부르면 로그가 실시간으로 붙는지 본다

- [ ] **Step 7: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 전부 PASS

- [ ] **Step 8: 커밋한다**

```bash
git add tests/test_acceptance.py tests/test_plugin_files.py \
        ../.claude-plugin/plugin.json ../../../README.md
git commit -m "feat(log): 크래시 인수 테스트와 플러그인 설정, 문서를 더한다"
```

> 경로는 `plugins/mcp-test/server/`에서 본 상대 경로다. 저장소 루트에서 커밋한다면 `git add -A` 후 확인한다.

---

## 실행 순서

Task 3 → Task 2 → Task 1 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8.

Task 2가 `logstream`을 import하고 `logpaths`를 import하므로 3과 1이 먼저다. 나머지는 번호 순서대로 하면 된다.

## 완료 기준

- `uv run pytest -q`가 전부 통과한다. 기존 78개가 하나도 깨지지 않는다.
- 스펙 §9.1의 8개 항목 각각에 대응하는 테스트가 있고, **일부러 구현을 되돌렸을 때 실제로 실패한다.** 되돌려 확인하지 않은 단언은 완료로 치지 않는다.
- 서버를 띄우면 `~/.mcp-test-server/logs/`에 파일이 생기고 관리 화면에 로그가 흐른다.
- 로그 어디에도 평문 토큰이 없다.
