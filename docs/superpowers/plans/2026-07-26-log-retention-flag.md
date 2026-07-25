# 로그 보관 기간 CLI 플래그 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 하드코딩된 72시간 로그 보관을 `--log-retention-days` 로 설정 가능하게 한다.

**Architecture:** `logpaths.MAX_AGE_SECONDS` 는 기본값으로 남기고, CLI 가 받은 값을 `main()` → `serve()` → 기동 직후 purge / `_purge_loop()` → `purge_logs(max_age_seconds=...)` 로 흘려보낸다. `purge_logs` 는 이미 `max_age_seconds` 를 키워드 인자로 받으므로 시그니처 변경이 없다.

**Tech Stack:** Python 3.11+, argparse, asyncio, pytest

**설계 스펙:** `docs/superpowers/specs/2026-07-26-log-retention-flag-design.md`. 그 문서의 원본은 이웃 저장소의 대조 설계 §8 이다 — `~/workspace/dev-exintueri/basic-channel-py-server/.claude/worktrees/channel-test-app/docs/superpowers/specs/2026-07-26-logging-admin-alignment-design.md` (브랜치 `feat/channel-test-app`, 아직 `main` 에 병합되지 않음).

## Global Constraints

- **`--log-retention-days` 는 `type=int`, 기본 `3`.** 스펙의 값을 그대로 옮긴 것이다
- **`0` 이하는 거부한다.** 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다
- **`MAX_AGE_SECONDS = 259200.0` 을 지우지 않는다.** 기본값의 단일 출처로 남긴다
- **`purge_logs` 의 시그니처를 바꾸지 않는다.** `max_age_seconds` 키워드가 이미 있다
- **커밋 시 `git add` 에 경로를 명시한다.** 이 저장소의 워킹 트리에는 이 계획과 무관한 미커밋 변경이 있다(`admin.py` / `tests/test_admin.py` 의 `_SESSION_POLL_MS`). `git add -A` 나 `git add .` 를 절대 쓰지 않는다

## 파일 구조

| 파일 | 책임 | 변경 |
|---|---|---|
| `plugins/mcp-test/server/src/mcp_test_server/__main__.py` | argparse → 검증 → `serve()` | 인자 추가, 검증, 전달 |
| `plugins/mcp-test/server/src/mcp_test_server/app.py` | `serve()`, `_purge_loop()` | 값을 받아 `purge_logs` 까지 전달 |
| `README.md` | 사용자 문서 | "72시간" 을 기본값 표기로 |
| `plugins/mcp-test/server/tests/test_cli.py` | CLI 검증 테스트 | 신규 또는 추가 |
| `plugins/mcp-test/server/tests/test_logpaths.py` | 보관 동작 테스트 | 추가 |

---

### Task 1: `--log-retention-days` 를 받아 `purge_logs` 까지 흘려보낸다

**Files:**
- Modify: `plugins/mcp-test/server/src/mcp_test_server/__main__.py`
- Modify: `plugins/mcp-test/server/src/mcp_test_server/app.py`
- Modify: `README.md:88`
- Test: `plugins/mcp-test/server/tests/test_cli.py`
- Test: `plugins/mcp-test/server/tests/test_logpaths.py`

**Interfaces:**
- Produces: `__main__.parse_args` 가 `args.log_retention_days: int` 를 갖는다
- Produces: `serve(*, host, port, admin_port, stale_after, handle=None, log_max_age_seconds: float = MAX_AGE_SECONDS)` — 기존 인자는 그대로다. 새 인자는 키워드 전용이고 기본값이 있으므로 기존 호출부와 테스트가 깨지지 않는다
- Produces: `_purge_loop(registry, clock, log_dir, log_file, max_age_seconds: float)` — 위치 인자로 하나 늘어난다. 이 함수는 `app.py` 안에서만 호출된다
- Consumes: `logpaths.purge_logs(log_dir, now, *, max_age_seconds=MAX_AGE_SECONDS, keep=None)` — 변경 없음

- [ ] **Step 1: 실패하는 테스트 작성 — CLI 검증**

`plugins/mcp-test/server/tests/test_cli.py` 가 이미 있으면 아래 테스트만 덧붙이고, 없으면 파일째 만든다.

```python
import pytest

from mcp_test_server.__main__ import parse_args


def test_log_retention_days_defaults_to_three():
    assert parse_args([]).log_retention_days == 3


def test_log_retention_days_accepts_a_positive_integer():
    assert parse_args(["--log-retention-days", "7"]).log_retention_days == 7


@pytest.mark.parametrize("value", ["0", "-1"])
def test_log_retention_days_rejects_zero_and_negative(value):
    # 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
    with pytest.raises(SystemExit) as exc:
        parse_args(["--log-retention-days", value])
    assert exc.value.code == 2
```

- [ ] **Step 2: 실패하는 테스트 작성 — 값이 실제 삭제 판정까지 도달하는지**

`plugins/mcp-test/server/tests/test_logpaths.py` 에 덧붙인다.

```python
from datetime import datetime, timedelta, timezone

from mcp_test_server.logpaths import log_file_name, purge_logs


def _log(log_dir, day_offset: int, hours_old: float, now: datetime):
    """LOG_GLOB 에 맞는 파일 하나를 만들고 mtime 을 hours_old 만큼 되돌린다."""
    path = log_dir / log_file_name(8765, (now + timedelta(days=day_offset)).date())
    path.write_text("x\n", encoding="utf-8")
    stamp = (now - timedelta(hours=hours_old)).timestamp()
    import os

    os.utime(path, (stamp, stamp))
    return path


def test_one_day_retention_deletes_two_day_old_and_keeps_twelve_hour_old(tmp_path):
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    old = _log(tmp_path, -2, 48, now)
    fresh = _log(tmp_path, 0, 12, now)

    removed, _ = purge_logs(tmp_path, now, max_age_seconds=1 * 86400)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_default_retention_is_still_seventy_two_hours(tmp_path):
    # 회귀. 플래그를 주지 않은 경로가 예전과 같아야 한다.
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    inside = _log(tmp_path, -2, 71, now)
    outside = _log(tmp_path, -4, 73, now)

    removed, _ = purge_logs(tmp_path, now)

    assert removed == 1
    assert inside.exists()
    assert not outside.exists()
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd plugins/mcp-test/server && uv run pytest tests/test_cli.py tests/test_logpaths.py -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'log_retention_days'` (CLI 쪽). `test_logpaths.py` 의 두 테스트는 `purge_logs` 가 이미 `max_age_seconds` 를 받으므로 통과할 수 있다. 통과하면 그대로 두고 CLI 쪽만 붉은 상태로 진행한다 — 이 두 테스트는 배선이 끊겼을 때를 잡는 회귀 그물이다.

- [ ] **Step 4: `__main__.py` 에 인자와 검증을 추가**

`parse_args` 안의 `--log-dir` 블록 **뒤**, `return parser.parse_args(argv)` **앞**에 넣는다.

```python
    parser.add_argument(
        "--log-retention-days",
        type=int,
        default=3,
        help="로그 파일을 며칠 보관할지. 이보다 오래된 파일을 지운다 (기본 3)",
    )
```

그리고 `return parser.parse_args(argv)` 를 다음으로 바꾼다.

```python
    args = parser.parse_args(argv)
    if args.log_retention_days <= 0:
        # 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
        parser.error("--log-retention-days 는 1 이상의 정수여야 한다")
    return args
```

`parser.error` 는 종료 코드 2로 `SystemExit` 을 던진다 — Step 1 의 테스트가 그 값을 확인한다.

- [ ] **Step 5: `main()` 이 값을 `serve()` 로 넘긴다**

`__main__.py` 의 `serve(...)` 호출에 한 줄 더한다.

```python
            serve(
                host=args.host,
                port=args.port,
                admin_port=args.admin_port,
                stale_after=args.stale_after,
                handle=handle,
                log_max_age_seconds=args.log_retention_days * 86400,
            )
```

- [ ] **Step 6: `app.py` 의 세 경유지를 배선**

`serve()` 시그니처에 키워드 인자를 더한다.

```python
async def serve(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
    handle: LoggingHandle | None = None,
    log_max_age_seconds: float = MAX_AGE_SECONDS,
) -> None:
```

`MAX_AGE_SECONDS` 를 `logpaths` 에서 import 한다 (`purge_logs` 를 이미 가져오는 그 줄에 붙인다).

기동 직후 1회 purge 에 전달한다.

```python
        _, warnings = purge_logs(
            log_dir, _utcnow(), keep=log_file(), max_age_seconds=log_max_age_seconds
        )
```

`_purge_loop` 태스크 생성에 전달한다.

```python
    purge = asyncio.create_task(
        _purge_loop(registry, _utcnow, log_dir, log_file, log_max_age_seconds)
    )
```

`_purge_loop` 가 받아서 쓴다.

```python
async def _purge_loop(
    registry: Registry,
    clock: Callable[[], datetime],
    log_dir: Path | None,
    log_file: Callable[[], Path | None],
    max_age_seconds: float,
) -> None:
```

그 안의 `purge_logs` 호출을 다음으로 바꾼다.

```python
            removed, warnings = purge_logs(
                log_dir, now, keep=log_file(), max_age_seconds=max_age_seconds
            )
```

- [ ] **Step 7: `README.md:88` 의 "72시간" 을 기본값 표기로**

Old:

```
- 보관 기간은 72시간이고, 마지막 수정 시각(mtime) 기준이다. 기동 시 한 번,
```

New:

```
- 보관 기간은 기본 72시간(`--log-retention-days 3`)이고, 마지막 수정
  시각(mtime) 기준이다. 기동 시 한 번,
```

- [ ] **Step 8: 전체 테스트 통과 확인**

Run: `cd plugins/mcp-test/server && uv run pytest -v`
Expected: 전체 통과. `serve()` 의 새 인자는 기본값이 있으므로 기존 `serve()` 호출 테스트가 그대로 통과해야 한다.

- [ ] **Step 9: 커밋**

경로를 명시한다. 이 저장소에는 이 계획과 무관한 미커밋 변경(`admin.py`, `tests/test_admin.py`)이 있으므로 `git add -A` 를 쓰면 남의 작업을 함께 커밋한다.

```bash
git add \
  plugins/mcp-test/server/src/mcp_test_server/__main__.py \
  plugins/mcp-test/server/src/mcp_test_server/app.py \
  plugins/mcp-test/server/tests/test_cli.py \
  plugins/mcp-test/server/tests/test_logpaths.py \
  README.md \
  docs/superpowers/plans/2026-07-26-log-retention-flag.md
git commit -m "feat(log): 보관 기간을 --log-retention-days 로 받는다"
```
