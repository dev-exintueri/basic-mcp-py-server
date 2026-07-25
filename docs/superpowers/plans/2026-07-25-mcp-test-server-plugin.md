# MCP 테스트 서버 플러그인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 여러 Claude Code 세션이 하나의 파이썬 프로세스에 HTTP MCP로 붙는 테스트 서버를 만들고, 이 저장소를 마켓플레이스로 삼아 플러그인으로 설치할 수 있게 한다.

**Architecture:** 한 프로세스에서 uvicorn 서버 두 개를 `asyncio.gather`로 돌린다. MCP 리스너(8765)는 `FastMCP.streamable_http_app()` 앞에 순수 ASGI 인증 미들웨어를 두고, 관리 리스너(8766)는 `127.0.0.1`에 고정 바인딩된 상태 페이지다. 두 앱은 프로세스 전역 `Registry` 인스턴스 하나만 공유하며, 세션 식별자는 플러그인의 `headersHelper`가 연결마다 발급하는 `X-Client-Instance` 헤더다.

**Tech Stack:** Python 3.11+, `mcp` 1.28.x (공식 SDK), Starlette, uvicorn, pytest + pytest-asyncio + httpx, uv

**설계 문서:** `docs/superpowers/specs/2026-07-25-mcp-test-server-plugin-design.md`

## Global Constraints

이 절의 내용은 모든 태스크의 요구사항에 암묵적으로 포함된다.

- **Python 3.11 이상.** `pyproject.toml`의 `requires-python = ">=3.11"`.
- **`mcp` 패키지 버전은 `>=1.28,<2`로 고정한다.** 아래 API 사실은 1.28.1 휠을 직접 열어 확인한 것이다. 다른 메이저 버전에서는 모듈 경로가 다르다.
  - `from mcp.server.fastmcp import FastMCP, Context`
  - `FastMCP.streamable_http_app() -> starlette.applications.Starlette` — `/mcp` 라우트와 lifespan을 포함한다
  - 도구 안에서 원본 요청은 `ctx.request_context.request` (Starlette `Request`, 없으면 `None`)
  - `await mcp.list_tools()` → `name` 속성을 가진 도구 목록
  - `await mcp.call_tool(name, arguments)` — 내부에서 `get_context()`를 부르므로 **요청 컨텍스트가 필요한 도구는 이 방식으로 단위 테스트할 수 없다.** 인자만 쓰는 도구(`echo`)만 가능하다
  - 클라이언트는 `from mcp.client.streamable_http import streamablehttp_client`, `streamablehttp_client(url, headers={...})`가 3-튜플을 반환한다
  - **`mcp.server.mcpserver`나 `MCPServer`는 1.28.1에 없다.** 그 이름은 아직 릴리스되지 않은 `main` 브랜치의 것이다. 쓰지 마라
- **인증 미들웨어는 `BaseHTTPMiddleware`가 아니라 순수 ASGI 미들웨어로 작성한다.** 요청 헤더만 읽고 응답은 건드리지 않으므로, 스트리밍 응답을 감싸는 데서 오는 문제를 원천적으로 피한다.
- **관리 리스너는 `127.0.0.1`에 고정 바인딩한다.** 이 주소를 바꾸는 CLI 인자나 설정을 만들지 마라.
- **세션 식별자는 `X-Client-Instance` 요청 헤더다.** `Mcp-Session-Id`는 기록만 하고 식별에 쓰지 않는다. MCP `2026-07-28` 개정판에는 세션이 없어 발급되지 않는다.
- **차단 응답은 `403`이다.** `404`가 아니다.
- **시간을 다루는 함수는 `now: datetime`을 인자로 받는다.** 테스트가 시간에 의존하지 않게 하기 위함이다. 내부에서 `datetime.now()`를 부르지 마라.
- 모든 서버 코드는 `plugins/mcp-test/server/` 아래에 둔다.
- 커밋 메시지는 한국어로 쓴다. 이 저장소의 기존 커밋과 같은 형식(`type: 요약`)을 따른다.

## File Structure

| 파일 | 책임 |
|---|---|
| `plugins/mcp-test/server/pyproject.toml` | 패키지 정의, 의존성, `mcp-test-server` 진입점 |
| `plugins/mcp-test/server/src/mcp_test_server/__init__.py` | 빈 패키지 마커 |
| `plugins/mcp-test/server/src/mcp_test_server/registry.py` | `SessionRecord`, `Registry`. 프로세스의 유일한 상태 보유자 |
| `plugins/mcp-test/server/src/mcp_test_server/auth.py` | `Identity`, `read_identity()`, `AuthMiddleware` |
| `plugins/mcp-test/server/src/mcp_test_server/mcp_server.py` | `build_mcp()` — FastMCP 인스턴스와 도구 4개 |
| `plugins/mcp-test/server/src/mcp_test_server/admin.py` | `build_admin_app()` — 관리 포트 Starlette 앱 |
| `plugins/mcp-test/server/src/mcp_test_server/app.py` | `serve()` — 두 앱 조립, 동시 기동, stale 스윕 |
| `plugins/mcp-test/server/src/mcp_test_server/__main__.py` | CLI 인자 파싱 |
| `plugins/mcp-test/server/tests/` | 위 각 모듈의 테스트 + 인수 테스트 |
| `plugins/mcp-test/.claude-plugin/plugin.json` | 플러그인 매니페스트, `userConfig` 선언 |
| `plugins/mcp-test/.mcp.json` | MCP 서버 등록 |
| `plugins/mcp-test/scripts/connection-id.sh` | `headersHelper` — 연결 ID 발급 |
| `plugins/mcp-test/hooks/hooks.json` | `SessionStart` 훅 선언 |
| `plugins/mcp-test/hooks/check-server.sh` | `CLAUDE_PLUGIN_OPTION_*` 환경변수 예시 |
| `plugins/mcp-test/commands/server-start.md` | `/mcp-test:server-start` |
| `plugins/mcp-test/commands/server-status.md` | `/mcp-test:server-status` |
| `.claude-plugin/marketplace.json` | 마켓플레이스 카탈로그 |
| `README.md` | 설치·기동·수동 검증 체크리스트 |

---

### Task 1: 패키지 스캐폴드와 세션 레지스트리

레지스트리는 프로세스의 유일한 상태 보유자다. 나머지 모듈이 전부 여기에 의존하므로 먼저 만든다.

**Files:**
- Create: `plugins/mcp-test/server/pyproject.toml`
- Create: `plugins/mcp-test/server/src/mcp_test_server/__init__.py`
- Create: `plugins/mcp-test/server/src/mcp_test_server/registry.py`
- Test: `plugins/mcp-test/server/tests/test_registry.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `SessionRecord` 데이터클래스 — 필드: `instance_id: str`, `subject: str`, `project: str`, `label: str`, `mcp_session_id: str | None`, `connected_at: datetime`, `last_seen: datetime`, `call_count: int`, `blocked: bool`
  - `Registry(stale_after: float = 300.0, purge_after: float = 86400.0)`
  - `Registry.touch(*, instance_id: str, subject: str, project: str, label: str, mcp_session_id: str | None, now: datetime) -> SessionRecord`
  - `Registry.get(instance_id: str) -> SessionRecord | None`
  - `Registry.all() -> list[SessionRecord]`
  - `Registry.remove(instance_id: str) -> bool`
  - `Registry.block(instance_id: str) -> bool`
  - `Registry.unblock(instance_id: str) -> bool`
  - `Registry.is_blocked(instance_id: str) -> bool`
  - `Registry.is_stale(record: SessionRecord, now: datetime) -> bool`
  - `Registry.purge(now: datetime) -> int`
  - `session_view(record: SessionRecord, registry: Registry, now: datetime) -> dict[str, object]` — 레코드를 JSON 직렬화 가능한 dict로 바꾸는 순수 함수. `mcp_server.py`(Task 3)와 `admin.py`(Task 4)가 함께 쓴다

**`session_view`가 여기 있는 이유:** `SessionRecord`와 `Registry`만 쓰는 순수 함수다. `mcp_server.py`에 두면 관리 앱이 MCP 모듈을, 따라서 SDK 전체를 끌어오게 된다. 관리 앱은 `registry`에만 의존해야 한다.

- [ ] **Step 1: 패키지 뼈대 만들기**

`plugins/mcp-test/server/pyproject.toml`:

```toml
[project]
name = "mcp-test-server"
version = "0.1.0"
description = "여러 Claude Code 세션이 하나의 프로세스에 붙는 MCP 테스트 서버"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.28,<2",
    "starlette>=0.37",
    "uvicorn>=0.31",
]

[project.scripts]
mcp-test-server = "mcp_test_server.__main__:main"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-timeout>=2.3",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_test_server"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`plugins/mcp-test/server/src/mcp_test_server/__init__.py`는 빈 파일로 만든다.

- [ ] **Step 2: 의존성 설치가 되는지 확인**

Run: `uv sync --directory plugins/mcp-test/server`
Expected: 성공. `plugins/mcp-test/server/.venv/`와 `uv.lock`이 생긴다.

- [ ] **Step 3: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_registry.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from mcp_test_server.registry import Registry, SessionRecord, session_view

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def touch(reg, instance_id="abc123", now=T0, **kwargs):
    defaults = dict(
        subject="alice",
        project="/tmp/proj",
        label="unnamed",
        mcp_session_id=None,
    )
    defaults.update(kwargs)
    return reg.touch(instance_id=instance_id, now=now, **defaults)


def test_touch_creates_record():
    reg = Registry()
    rec = touch(reg)
    assert isinstance(rec, SessionRecord)
    assert rec.instance_id == "abc123"
    assert rec.subject == "alice"
    assert rec.connected_at == T0
    assert rec.last_seen == T0
    assert rec.call_count == 1
    assert rec.blocked is False


def test_touch_twice_updates_last_seen_and_count():
    reg = Registry()
    touch(reg)
    later = T0 + timedelta(seconds=30)
    rec = touch(reg, now=later)
    assert rec.connected_at == T0
    assert rec.last_seen == later
    assert rec.call_count == 2
    assert len(reg.all()) == 1


def test_touch_records_mcp_session_id_when_present():
    reg = Registry()
    rec = touch(reg, mcp_session_id="legacy-sid")
    assert rec.mcp_session_id == "legacy-sid"


def test_distinct_instances_are_separate_records():
    reg = Registry()
    touch(reg, instance_id="one")
    touch(reg, instance_id="two")
    assert {r.instance_id for r in reg.all()} == {"one", "two"}


def test_get_and_remove():
    reg = Registry()
    touch(reg)
    assert reg.get("abc123") is not None
    assert reg.remove("abc123") is True
    assert reg.get("abc123") is None
    assert reg.remove("abc123") is False


def test_block_and_unblock():
    reg = Registry()
    touch(reg)
    assert reg.is_blocked("abc123") is False
    assert reg.block("abc123") is True
    assert reg.is_blocked("abc123") is True
    assert reg.get("abc123").blocked is True
    assert reg.unblock("abc123") is True
    assert reg.is_blocked("abc123") is False


def test_block_unknown_instance_returns_false():
    reg = Registry()
    assert reg.block("nope") is False
    assert reg.unblock("nope") is False


def test_is_stale_uses_stale_after():
    reg = Registry(stale_after=300.0)
    rec = touch(reg)
    assert reg.is_stale(rec, T0 + timedelta(seconds=299)) is False
    assert reg.is_stale(rec, T0 + timedelta(seconds=301)) is True


def test_purge_removes_only_records_past_purge_after():
    reg = Registry(stale_after=300.0, purge_after=86400.0)
    touch(reg, instance_id="old")
    touch(reg, instance_id="fresh", now=T0 + timedelta(hours=23))
    removed = reg.purge(T0 + timedelta(hours=24, seconds=1))
    assert removed == 1
    assert {r.instance_id for r in reg.all()} == {"fresh"}


def test_session_view_serialises_a_record():
    reg = Registry(stale_after=300.0)
    view = session_view(touch(reg), reg, now=T0)
    assert view["instance_id"] == "abc123"
    assert view["subject"] == "alice"
    assert view["project"] == "/tmp/proj"
    assert view["label"] == "unnamed"
    assert view["mcp_session_id"] is None
    assert view["call_count"] == 1
    assert view["blocked"] is False
    assert view["stale"] is False
    assert view["connected_at"] == T0.isoformat()
    assert view["last_seen"] == T0.isoformat()


def test_session_view_marks_stale_records():
    reg = Registry(stale_after=300.0)
    record = touch(reg)
    assert session_view(record, reg, now=T0 + timedelta(seconds=301))["stale"] is True
```

- [ ] **Step 4: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.registry'`

- [ ] **Step 5: 레지스트리 구현**

`plugins/mcp-test/server/src/mcp_test_server/registry.py`:

```python
"""세션 레지스트리. 이 프로세스의 유일한 상태 보유자다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionRecord:
    """하나의 Claude Code 연결. instance_id 하나에 레코드 하나가 대응한다."""

    instance_id: str
    subject: str
    project: str
    label: str
    mcp_session_id: str | None
    connected_at: datetime
    last_seen: datetime
    call_count: int
    blocked: bool


class Registry:
    """세션 레코드와 차단 상태를 들고 있는다.

    두 ASGI 앱이 같은 이벤트 루프에서 이 인스턴스 하나를 공유한다.
    별도의 락은 두지 않는다.
    """

    def __init__(self, stale_after: float = 300.0, purge_after: float = 86400.0) -> None:
        self._records: dict[str, SessionRecord] = {}
        self.stale_after = stale_after
        self.purge_after = purge_after

    def touch(
        self,
        *,
        instance_id: str,
        subject: str,
        project: str,
        label: str,
        mcp_session_id: str | None,
        now: datetime,
    ) -> SessionRecord:
        """요청 하나를 반영한다. 없으면 만들고 있으면 갱신한다."""
        record = self._records.get(instance_id)
        if record is None:
            record = SessionRecord(
                instance_id=instance_id,
                subject=subject,
                project=project,
                label=label,
                mcp_session_id=mcp_session_id,
                connected_at=now,
                last_seen=now,
                call_count=1,
                blocked=False,
            )
            self._records[instance_id] = record
            return record

        record.last_seen = now
        record.call_count += 1
        record.subject = subject
        record.project = project
        record.label = label
        if mcp_session_id is not None:
            record.mcp_session_id = mcp_session_id
        return record

    def get(self, instance_id: str) -> SessionRecord | None:
        return self._records.get(instance_id)

    def all(self) -> list[SessionRecord]:
        return list(self._records.values())

    def remove(self, instance_id: str) -> bool:
        return self._records.pop(instance_id, None) is not None

    def block(self, instance_id: str) -> bool:
        record = self._records.get(instance_id)
        if record is None:
            return False
        record.blocked = True
        return True

    def unblock(self, instance_id: str) -> bool:
        record = self._records.get(instance_id)
        if record is None:
            return False
        record.blocked = False
        return True

    def is_blocked(self, instance_id: str) -> bool:
        record = self._records.get(instance_id)
        return record is not None and record.blocked

    def is_stale(self, record: SessionRecord, now: datetime) -> bool:
        return (now - record.last_seen).total_seconds() > self.stale_after

    def purge(self, now: datetime) -> int:
        """purge_after를 넘긴 레코드를 제거하고 제거한 개수를 반환한다."""
        doomed = [
            instance_id
            for instance_id, record in self._records.items()
            if (now - record.last_seen).total_seconds() > self.purge_after
        ]
        for instance_id in doomed:
            del self._records[instance_id]
        return len(doomed)


def session_view(
    record: SessionRecord, registry: Registry, now: datetime
) -> dict[str, object]:
    """세션 레코드를 JSON으로 옮길 수 있는 형태로 바꾼다.

    MCP 도구와 관리 앱이 같은 표현을 쓰도록 여기 한 곳에만 둔다.
    """
    return {
        "instance_id": record.instance_id,
        "subject": record.subject,
        "project": record.project,
        "label": record.label,
        "mcp_session_id": record.mcp_session_id,
        "connected_at": record.connected_at.isoformat(),
        "last_seen": record.last_seen.isoformat(),
        "call_count": record.call_count,
        "blocked": record.blocked,
        "stale": registry.is_stale(record, now),
    }
```

- [ ] **Step 6: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_registry.py -v`
Expected: PASS — 11개 통과

- [ ] **Step 7: 커밋**

```bash
git add plugins/mcp-test/server/pyproject.toml \
        plugins/mcp-test/server/uv.lock \
        plugins/mcp-test/server/src/mcp_test_server/__init__.py \
        plugins/mcp-test/server/src/mcp_test_server/registry.py \
        plugins/mcp-test/server/tests/test_registry.py
git commit -m "feat(server): 세션 레지스트리와 패키지 뼈대를 만든다"
```

---

### Task 2: 인증·차단 ASGI 미들웨어

요청 헤더에서 신원을 읽고, 인증을 검사하고, 차단된 연결을 막고, 레지스트리를 갱신한다.

**Files:**
- Create: `plugins/mcp-test/server/src/mcp_test_server/auth.py`
- Test: `plugins/mcp-test/server/tests/test_auth.py`

**Interfaces:**
- Consumes: `Registry`, `SessionRecord` (Task 1)
- Produces:
  - `UNKNOWN_INSTANCE: str = "unknown"`
  - `Identity` 데이터클래스 (frozen) — `subject: str`, `instance_id: str`, `project: str`, `label: str`, `mcp_session_id: str | None`
  - `read_identity(headers: Mapping[str, str]) -> Identity | None` — 인증 실패면 `None`
  - `AuthMiddleware(app, registry: Registry, clock: Callable[[], datetime])` — 순수 ASGI 미들웨어

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_auth.py`:

```python
from datetime import datetime, timezone

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from mcp_test_server.auth import UNKNOWN_INSTANCE, AuthMiddleware, read_identity
from mcp_test_server.registry import Registry

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)

FULL_HEADERS = {
    "authorization": "Bearer alice",
    "x-client-instance": "abc123",
    "x-client-project": "/tmp/proj",
    "x-client-label": "left",
}


# --- read_identity ---


def test_read_identity_parses_all_headers():
    identity = read_identity(FULL_HEADERS)
    assert identity is not None
    assert identity.subject == "alice"
    assert identity.instance_id == "abc123"
    assert identity.project == "/tmp/proj"
    assert identity.label == "left"
    assert identity.mcp_session_id is None


def test_read_identity_picks_up_mcp_session_id():
    identity = read_identity({**FULL_HEADERS, "mcp-session-id": "legacy"})
    assert identity.mcp_session_id == "legacy"


@pytest.mark.parametrize(
    "authorization",
    [None, "", "alice", "Bearer", "Bearer ", "Bearer    ", "Bearer \t "],
)
def test_read_identity_rejects_blank_or_malformed_token(authorization):
    headers = dict(FULL_HEADERS)
    if authorization is None:
        del headers["authorization"]
    else:
        headers["authorization"] = authorization
    assert read_identity(headers) is None


def test_read_identity_strips_surrounding_whitespace_from_token():
    identity = read_identity({**FULL_HEADERS, "authorization": "Bearer   alice  "})
    assert identity.subject == "alice"


def test_read_identity_defaults_missing_optional_headers():
    identity = read_identity({"authorization": "Bearer alice"})
    assert identity.instance_id == UNKNOWN_INSTANCE
    assert identity.project == ""
    assert identity.label == "unnamed"


# --- AuthMiddleware ---


def build_client(registry, clock=lambda: T0):
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/mcp", ok, methods=["POST", "DELETE"])])
    app = AuthMiddleware(inner, registry=registry, clock=clock)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_valid_request_passes_and_is_recorded():
    registry = Registry()
    async with build_client(registry) as client:
        response = await client.post("/mcp", headers=FULL_HEADERS)
    assert response.status_code == 200
    record = registry.get("abc123")
    assert record is not None
    assert record.subject == "alice"
    assert record.call_count == 1


async def test_missing_authorization_is_401_with_challenge():
    registry = Registry()
    headers = {k: v for k, v in FULL_HEADERS.items() if k != "authorization"}
    async with build_client(registry) as client:
        response = await client.post("/mcp", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert registry.all() == []


async def test_blank_token_is_401():
    registry = Registry()
    async with build_client(registry) as client:
        response = await client.post(
            "/mcp", headers={**FULL_HEADERS, "authorization": "Bearer    "}
        )
    assert response.status_code == 401


async def test_blocked_instance_gets_403():
    registry = Registry()
    async with build_client(registry) as client:
        await client.post("/mcp", headers=FULL_HEADERS)
        registry.block("abc123")
        response = await client.post("/mcp", headers=FULL_HEADERS)
    assert response.status_code == 403


async def test_missing_instance_header_is_recorded_as_unknown():
    registry = Registry()
    headers = {k: v for k, v in FULL_HEADERS.items() if k != "x-client-instance"}
    async with build_client(registry) as client:
        response = await client.post("/mcp", headers=headers)
    assert response.status_code == 200
    assert registry.get(UNKNOWN_INSTANCE) is not None


async def test_delete_removes_the_record():
    registry = Registry()
    async with build_client(registry) as client:
        await client.post("/mcp", headers=FULL_HEADERS)
        assert registry.get("abc123") is not None
        response = await client.request("DELETE", "/mcp", headers=FULL_HEADERS)
    assert response.status_code == 200
    assert registry.get("abc123") is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.auth'`

- [ ] **Step 3: 미들웨어 구현**

`plugins/mcp-test/server/src/mcp_test_server/auth.py`:

```python
"""인증·차단 미들웨어와 요청 신원 파싱.

미들웨어는 순수 ASGI다. BaseHTTPMiddleware를 쓰지 않는 이유는 응답을 감싸지
않기 위해서다. 요청 헤더만 읽고 응답에는 손대지 않으므로 스트리밍 응답과
얽히지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .registry import Registry

UNKNOWN_INSTANCE = "unknown"
_BEARER_PREFIX = "bearer "


@dataclass(frozen=True)
class Identity:
    """요청 헤더에서 읽어낸 호출자 신원."""

    subject: str
    instance_id: str
    project: str
    label: str
    mcp_session_id: str | None


def read_identity(headers: Mapping[str, str]) -> Identity | None:
    """헤더에서 신원을 읽는다. 인증에 실패하면 None을 반환한다.

    통과 조건은 하나뿐이다 — Bearer 뒤 문자열이 공백을 제거하고도 남아 있을 것.
    테스트 서버이므로 값을 비교하지 않는다.
    """
    authorization = headers.get("authorization")
    if authorization is None:
        return None
    if not authorization.lower().startswith(_BEARER_PREFIX):
        return None

    subject = authorization[len(_BEARER_PREFIX) :].strip()
    if not subject:
        return None

    return Identity(
        subject=subject,
        instance_id=headers.get("x-client-instance") or UNKNOWN_INSTANCE,
        project=headers.get("x-client-project") or "",
        label=headers.get("x-client-label") or "unnamed",
        mcp_session_id=headers.get("mcp-session-id"),
    )


class AuthMiddleware:
    """MCP 앱 앞에 서서 인증하고, 차단하고, 레지스트리를 갱신한다."""

    def __init__(
        self,
        app: ASGIApp,
        registry: Registry,
        clock: Callable[[], datetime],
    ) -> None:
        self.app = app
        self.registry = registry
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        identity = read_identity(Headers(scope=scope))
        if identity is None:
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
            await self._reject(
                scope,
                receive,
                send,
                status=403,
                detail=f"연결 {identity.instance_id} 이(가) 관리 화면에서 차단되었다",
            )
            return

        if scope["method"] == "DELETE":
            self.registry.remove(identity.instance_id)
            await self.app(scope, receive, send)
            return

        self.registry.touch(
            instance_id=identity.instance_id,
            subject=identity.subject,
            project=identity.project,
            label=identity.label,
            mcp_session_id=identity.mcp_session_id,
            now=self.clock(),
        )
        await self.app(scope, receive, send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status: int,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        response = JSONResponse(
            {"error": detail}, status_code=status, headers=headers
        )
        await response(scope, receive, send)
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_auth.py -v`
Expected: PASS — 16개 통과 (파라미터화된 7개 포함)

- [ ] **Step 5: 커밋**

```bash
git add plugins/mcp-test/server/src/mcp_test_server/auth.py \
        plugins/mcp-test/server/tests/test_auth.py
git commit -m "feat(server): 인증과 차단을 처리하는 ASGI 미들웨어를 만든다"
```

---

### Task 3: MCP 서버와 도구 4개

**Files:**
- Create: `plugins/mcp-test/server/src/mcp_test_server/mcp_server.py`
- Test: `plugins/mcp-test/server/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `Registry`, `session_view` (Task 1), `read_identity`, `UNKNOWN_INSTANCE` (Task 2)
- Produces:
  - `build_mcp(registry: Registry, started_at: datetime, clock: Callable[[], datetime]) -> FastMCP`
  - 도구 이름: `ping`, `echo`, `whoami`, `sessions`

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_mcp_server.py`:

```python
import os
from datetime import datetime, timedelta, timezone

from mcp_test_server.mcp_server import build_mcp
from mcp_test_server.registry import Registry

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def make_registry():
    registry = Registry(stale_after=300.0)
    registry.touch(
        instance_id="abc123",
        subject="alice",
        project="/tmp/proj",
        label="left",
        mcp_session_id=None,
        now=T0,
    )
    return registry


async def test_server_exposes_exactly_four_tools():
    mcp = build_mcp(make_registry(), started_at=T0, clock=lambda: T0)
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == {"ping", "echo", "whoami", "sessions"}


async def test_echo_returns_the_same_text():
    mcp = build_mcp(make_registry(), started_at=T0, clock=lambda: T0)
    result = await mcp.call_tool("echo", {"text": "안녕"})
    assert "안녕" in str(result)


async def test_ping_reports_this_process_pid():
    mcp = build_mcp(
        make_registry(), started_at=T0, clock=lambda: T0 + timedelta(seconds=42)
    )
    result = await mcp.call_tool("ping", {})
    assert str(os.getpid()) in str(result)
```

`whoami`와 `sessions`는 요청 컨텍스트가 필요하므로 여기서 호출할 수 없다. Task 6의 인수 테스트에서 실제 클라이언트로 검증한다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_mcp_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.mcp_server'`

- [ ] **Step 3: MCP 서버 구현**

`plugins/mcp-test/server/src/mcp_test_server/mcp_server.py`:

```python
"""FastMCP 인스턴스와 노출 도구 4개."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime

from mcp.server.fastmcp import Context, FastMCP

from .auth import UNKNOWN_INSTANCE, read_identity
from .registry import Registry, session_view


def _instance_id_of(ctx: Context) -> str:
    """현재 요청의 연결 ID를 읽는다.

    미들웨어가 쓴 것과 같은 헤더를 같은 함수로 읽으므로 두 곳의 판단이
    갈라지지 않는다.
    """
    request = ctx.request_context.request
    if request is None:
        return UNKNOWN_INSTANCE
    identity = read_identity(request.headers)
    return identity.instance_id if identity else UNKNOWN_INSTANCE


def build_mcp(
    registry: Registry,
    started_at: datetime,
    clock: Callable[[], datetime],
) -> FastMCP:
    mcp = FastMCP("mcp-test-server")

    @mcp.tool()
    def ping() -> dict[str, object]:
        """서버 프로세스 정보를 반환한다. 여러 세션이 같은 pid를 보면 한 프로세스를 공유하는 것이다."""
        now = clock()
        return {
            "pid": os.getpid(),
            "uptime_seconds": (now - started_at).total_seconds(),
            "session_count": len(registry.all()),
            "server_time": now.isoformat(),
        }

    @mcp.tool()
    def echo(text: str) -> str:
        """받은 문자열을 그대로 돌려준다."""
        return text

    @mcp.tool()
    def whoami(ctx: Context) -> dict[str, object]:
        """이 세션이 서버에 어떻게 보이는지 반환한다."""
        instance_id = _instance_id_of(ctx)
        record = registry.get(instance_id)
        if record is None:
            return {"instance_id": instance_id, "known": False}
        return {"known": True, **session_view(record, registry, clock())}

    @mcp.tool()
    def sessions() -> dict[str, object]:
        """이 서버에 붙어 있는 모든 세션을 반환한다."""
        now = clock()
        return {
            "count": len(registry.all()),
            "sessions": [
                session_view(record, registry, now) for record in registry.all()
            ],
        }

    return mcp
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_mcp_server.py -v`
Expected: PASS — 3개 통과

- [ ] **Step 5: 커밋**

```bash
git add plugins/mcp-test/server/src/mcp_test_server/mcp_server.py \
        plugins/mcp-test/server/tests/test_mcp_server.py
git commit -m "feat(server): MCP 도구 ping·echo·whoami·sessions를 만든다"
```

---

### Task 4: 관리 포트 앱

**Files:**
- Create: `plugins/mcp-test/server/src/mcp_test_server/admin.py`
- Test: `plugins/mcp-test/server/tests/test_admin.py`

**Interfaces:**
- Consumes: `Registry`, `session_view` (Task 1). **`mcp_server`를 임포트하지 않는다** — 관리 앱이 MCP SDK를 끌어올 이유가 없다
- Produces:
  - `build_admin_app(registry: Registry, started_at: datetime, clock: Callable[[], datetime], mcp_endpoint: str) -> Starlette`
  - 라우트: `GET /`, `GET /api/status`, `POST /api/sessions/{instance_id}/block`, `POST /api/sessions/{instance_id}/unblock`

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_admin.py`:

```python
from datetime import datetime, timezone

import httpx

from mcp_test_server.admin import build_admin_app
from mcp_test_server.registry import Registry

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def build_client(registry):
    app = build_admin_app(
        registry,
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    )


def make_registry():
    registry = Registry()
    registry.touch(
        instance_id="abc123",
        subject="alice",
        project="/tmp/proj",
        label="left",
        mcp_session_id=None,
        now=T0,
    )
    return registry


async def test_status_returns_server_info_and_sessions():
    async with build_client(make_registry()) as client:
        response = await client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["pid"] > 0
    assert body["mcp_endpoint"] == "http://127.0.0.1:8765/mcp"
    assert body["session_count"] == 1
    assert body["sessions"][0]["instance_id"] == "abc123"


async def test_block_marks_the_session():
    registry = make_registry()
    async with build_client(registry) as client:
        response = await client.post("/api/sessions/abc123/block")
    assert response.status_code == 200
    assert registry.is_blocked("abc123") is True


async def test_unblock_clears_the_flag():
    registry = make_registry()
    registry.block("abc123")
    async with build_client(registry) as client:
        response = await client.post("/api/sessions/abc123/unblock")
    assert response.status_code == 200
    assert registry.is_blocked("abc123") is False


async def test_block_unknown_session_is_404():
    async with build_client(make_registry()) as client:
        response = await client.post("/api/sessions/nope/block")
    assert response.status_code == 404
    assert "error" in response.json()


async def test_index_page_lists_sessions_as_html():
    async with build_client(make_registry()) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "abc123" in response.text
    assert "alice" in response.text


async def test_index_page_escapes_session_values():
    registry = Registry()
    registry.touch(
        instance_id="abc123",
        subject="<script>alert(1)</script>",
        project="/tmp/proj",
        label="left",
        mcp_session_id=None,
        now=T0,
    )
    async with build_client(registry) as client:
        response = await client.get("/")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_admin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.admin'`

- [ ] **Step 3: 관리 앱 구현**

`plugins/mcp-test/server/src/mcp_test_server/admin.py`:

```python
"""관리 포트 앱. 127.0.0.1에만 바인딩되며 인증하지 않는다.

인증이 없는 이유는 브라우저가 URL을 여는 것만으로 Authorization 헤더를
붙일 수 없기 때문이다. 그 대가로 이 앱은 루프백 밖으로 나가지 않는다.
"""

from __future__ import annotations

import html
import os
from collections.abc import Callable
from datetime import datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from .registry import Registry, session_view

_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>MCP 테스트 서버</title>
<style>
body {{ font-family: ui-monospace, monospace; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; }}
.stale {{ color: #888; }}
.blocked {{ background: #fee; }}
.note {{ color: #666; font-size: .9rem; }}
</style>
</head>
<body>
<h1>MCP 테스트 서버</h1>
<p>pid {pid} · uptime {uptime:.0f}s · MCP {endpoint} · 세션 {count}개</p>
<p class="note">차단하면 그 세션은 403을 받고, Claude Code가 headersHelper를
다시 실행해 <b>새 연결 ID로 되살아난다.</b> 레코드가 사라지고 새 줄이
나타나는 것이 정상이다.</p>
<table>
<tr><th>연결 ID</th><th>subject</th><th>project</th><th>label</th>
<th>연결 시각</th><th>마지막 호출</th><th>호출</th><th></th></tr>
{rows}
</table>
</body>
</html>
"""

_ROW = """<tr class="{classes}">
<td>{instance_id}</td><td>{subject}</td><td>{project}</td><td>{label}</td>
<td>{connected_at}</td><td>{last_seen}</td><td>{call_count}</td>
<td><form method="post" action="/api/sessions/{instance_id}/{action}">
<button type="submit">{action_label}</button></form></td>
</tr>
"""


def build_admin_app(
    registry: Registry,
    started_at: datetime,
    clock: Callable[[], datetime],
    mcp_endpoint: str,
) -> Starlette:
    def _snapshot() -> tuple[datetime, list[dict[str, object]]]:
        now = clock()
        return now, [session_view(r, registry, now) for r in registry.all()]

    async def status(request: Request) -> JSONResponse:
        now, views = _snapshot()
        return JSONResponse(
            {
                "pid": os.getpid(),
                "uptime_seconds": (now - started_at).total_seconds(),
                "mcp_endpoint": mcp_endpoint,
                "session_count": len(views),
                "sessions": views,
            }
        )

    async def index(request: Request) -> HTMLResponse:
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
        return HTMLResponse(
            _PAGE.format(
                pid=os.getpid(),
                uptime=(now - started_at).total_seconds(),
                endpoint=html.escape(mcp_endpoint),
                count=len(views),
                rows=rows,
            )
        )

    def _toggle(action: str) -> Callable[[Request], object]:
        async def handler(request: Request):
            instance_id = request.path_params["instance_id"]
            changed = (
                registry.block(instance_id)
                if action == "block"
                else registry.unblock(instance_id)
            )
            if not changed:
                return JSONResponse(
                    {"error": f"알 수 없는 연결 ID: {instance_id}"}, status_code=404
                )
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/", status_code=303)
            return JSONResponse({"instance_id": instance_id, "action": action})

        return handler

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route(
                "/api/sessions/{instance_id}/block", _toggle("block"), methods=["POST"]
            ),
            Route(
                "/api/sessions/{instance_id}/unblock",
                _toggle("unblock"),
                methods=["POST"],
            ),
        ]
    )
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_admin.py -v`
Expected: PASS — 6개 통과

- [ ] **Step 5: 커밋**

```bash
git add plugins/mcp-test/server/src/mcp_test_server/admin.py \
        plugins/mcp-test/server/tests/test_admin.py
git commit -m "feat(server): 상태 조회와 세션 차단을 위한 관리 포트를 만든다"
```

---

### Task 5: 두 리스너 조립과 CLI

**Files:**
- Create: `plugins/mcp-test/server/src/mcp_test_server/app.py`
- Create: `plugins/mcp-test/server/src/mcp_test_server/__main__.py`
- Test: `plugins/mcp-test/server/tests/test_app.py`

**Interfaces:**
- Consumes: `Registry` (Task 1), `AuthMiddleware` (Task 2), `build_mcp` (Task 3), `build_admin_app` (Task 4)
- Produces:
  - `DEFAULTS: dict` — `{"host": "127.0.0.1", "port": 8765, "admin_port": 8766, "stale_after": 300.0}`
  - `ADMIN_HOST: str = "127.0.0.1"` — 상수. 바꿀 수 있는 통로를 만들지 않는다
  - `build_stack(host, port, admin_port, stale_after, clock) -> tuple[ASGIApp, Starlette, Registry]` — `(mcp_app, admin_app, registry)`
  - `PortInUse(OSError)` 예외
  - `ensure_port_free(host: str, port: int) -> None` — 쓸 수 있으면 조용히 반환, 아니면 `PortInUse`
  - `async serve(host, port, admin_port, stale_after) -> None`
  - `main(argv: list[str] | None = None) -> int` (`__main__.py`)

**포트 충돌을 미리 확인하는 이유:** uvicorn은 바인딩에 실패하면 로그를 남기고 `sys.exit(1)`을 호출한다. `SystemExit`은 `BaseException`이라 `except OSError`로 잡히지 않고, 우리가 준비한 안내 메시지도 출력되지 않는다. 기동 전에 직접 확인하면 메시지를 우리가 통제할 수 있고 테스트도 결정적이 된다.

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_app.py`:

```python
from datetime import datetime, timezone

import httpx
import pytest

from mcp_test_server.__main__ import parse_args
from mcp_test_server.app import (
    ADMIN_HOST,
    DEFAULTS,
    PortInUse,
    build_stack,
    ensure_port_free,
)

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def test_admin_host_is_loopback_only():
    assert ADMIN_HOST == "127.0.0.1"


def test_defaults_match_the_spec():
    assert DEFAULTS == {
        "host": "127.0.0.1",
        "port": 8765,
        "admin_port": 8766,
        "stale_after": 300.0,
    }


def test_parse_args_uses_defaults():
    args = parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.admin_port == 8766
    assert args.stale_after == 300.0


def test_parse_args_accepts_overrides():
    args = parse_args(["--host", "0.0.0.0", "--port", "9000", "--admin-port", "9001"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.admin_port == 9001


def test_parse_args_rejects_an_admin_host_flag():
    with pytest.raises(SystemExit):
        parse_args(["--admin-host", "0.0.0.0"])


def test_ensure_port_free_passes_for_an_unused_port():
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    ensure_port_free("127.0.0.1", port)  # 예외가 나지 않으면 통과


def test_ensure_port_free_raises_for_a_bound_port():
    import socket

    with socket.socket() as taken:
        taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        with pytest.raises(PortInUse) as excinfo:
            ensure_port_free("127.0.0.1", port)
    assert str(port) in str(excinfo.value)


def test_build_stack_shares_one_registry():
    mcp_app, admin_app, registry = build_stack(
        host="127.0.0.1",
        port=8765,
        admin_port=8766,
        stale_after=300.0,
        clock=lambda: T0,
    )
    assert mcp_app is not None
    assert admin_app is not None
    assert registry.all() == []


async def test_mcp_app_rejects_unauthenticated_requests():
    mcp_app, _, _ = build_stack(
        host="127.0.0.1",
        port=8765,
        admin_port=8766,
        stale_after=300.0,
        clock=lambda: T0,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://test"
    ) as client:
        response = await client.post("/mcp", json={})
    assert response.status_code == 401


async def test_admin_app_reports_the_mcp_endpoint():
    _, admin_app, _ = build_stack(
        host="127.0.0.1",
        port=9000,
        admin_port=9001,
        stale_after=300.0,
        clock=lambda: T0,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app), base_url="http://admin"
    ) as client:
        body = (await client.get("/api/status")).json()
    assert body["mcp_endpoint"] == "http://127.0.0.1:9000/mcp"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_test_server.app'`

- [ ] **Step 3: 조립 모듈 구현**

`plugins/mcp-test/server/src/mcp_test_server/app.py`:

```python
"""두 ASGI 앱을 조립하고 한 프로세스에서 함께 기동한다."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from datetime import datetime, timezone

import uvicorn
from starlette.applications import Starlette
from starlette.types import ASGIApp

from .admin import build_admin_app
from .auth import AuthMiddleware
from .mcp_server import build_mcp
from .registry import Registry

# 관리 리스너는 루프백에 고정한다. 인증이 없는 리스너이므로 이 값을
# 바꿀 수 있는 통로를 만들지 않는다.
ADMIN_HOST = "127.0.0.1"

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8765,
    "admin_port": 8766,
    "stale_after": 300.0,
}

_PURGE_INTERVAL_SECONDS = 600.0


class PortInUse(OSError):
    """기동 전 포트 확인에서 이미 사용 중임을 발견했을 때."""


def ensure_port_free(host: str, port: int) -> None:
    """포트를 쓸 수 있는지 미리 확인한다.

    uvicorn은 바인딩에 실패하면 sys.exit(1)을 호출한다. SystemExit은
    BaseException이라 except OSError로 잡히지 않고 우리 안내 메시지도
    출력되지 않는다. 기동 전에 직접 확인해 메시지를 통제한다.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise PortInUse(f"{host}:{port} 이(가) 이미 사용 중이다") from exc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_stack(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
    clock: Callable[[], datetime] = _utcnow,
) -> tuple[ASGIApp, Starlette, Registry]:
    """MCP 앱, 관리 앱, 그리고 둘이 공유하는 레지스트리를 만든다."""
    started_at = clock()
    registry = Registry(stale_after=stale_after)

    mcp = build_mcp(registry, started_at=started_at, clock=clock)
    mcp_app = AuthMiddleware(
        mcp.streamable_http_app(), registry=registry, clock=clock
    )

    admin_app = build_admin_app(
        registry,
        started_at=started_at,
        clock=clock,
        mcp_endpoint=f"http://{host}:{port}/mcp",
    )
    return mcp_app, admin_app, registry


async def _purge_loop(registry: Registry) -> None:
    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        registry.purge(_utcnow())


async def serve(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
) -> None:
    """두 리스너를 동시에 띄운다. 하나가 죽으면 함께 끝난다."""
    ensure_port_free(host, port)
    ensure_port_free(ADMIN_HOST, admin_port)

    mcp_app, admin_app, registry = build_stack(
        host=host, port=port, admin_port=admin_port, stale_after=stale_after
    )

    mcp_server = uvicorn.Server(
        uvicorn.Config(mcp_app, host=host, port=port, log_level="info")
    )
    admin_server = uvicorn.Server(
        uvicorn.Config(admin_app, host=ADMIN_HOST, port=admin_port, log_level="warning")
    )

    print(f"MCP    http://{host}:{port}/mcp")
    print(f"관리   http://{ADMIN_HOST}:{admin_port}/")

    purge = asyncio.create_task(_purge_loop(registry))
    try:
        await asyncio.gather(mcp_server.serve(), admin_server.serve())
    finally:
        purge.cancel()
```

`plugins/mcp-test/server/src/mcp_test_server/__main__.py`:

```python
"""CLI 진입점."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .app import DEFAULTS, PortInUse, serve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mcp-test-server",
        description="여러 Claude Code 세션이 공유하는 MCP 테스트 서버",
    )
    parser.add_argument("--host", default=DEFAULTS["host"], help="MCP 리스너 바인딩 주소")
    parser.add_argument("--port", type=int, default=DEFAULTS["port"], help="MCP 리스너 포트")
    parser.add_argument(
        "--admin-port",
        type=int,
        default=DEFAULTS["admin_port"],
        help="관리 리스너 포트 (주소는 127.0.0.1 고정)",
    )
    parser.add_argument(
        "--stale-after",
        type=float,
        default=DEFAULTS["stale_after"],
        help="이 시간(초) 동안 호출이 없으면 stale로 표시한다",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(
            serve(
                host=args.host,
                port=args.port,
                admin_port=args.admin_port,
                stale_after=args.stale_after,
            )
        )
    except PortInUse as exc:
        print(f"기동 실패: {exc}", file=sys.stderr)
        print("--port 또는 --admin-port 로 다른 포트를 지정하라.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_app.py -v`
Expected: PASS — 10개 통과

- [ ] **Step 5: 실제로 기동되는지 눈으로 확인**

Run: `uv run --directory plugins/mcp-test/server mcp-test-server --port 8765 --admin-port 8766`
Expected: `MCP    http://127.0.0.1:8765/mcp`와 `관리   http://127.0.0.1:8766/` 두 줄이 찍히고 프로세스가 유지된다.

다른 터미널에서:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8765/mcp   # 401
curl -s http://127.0.0.1:8766/api/status                                      # JSON
```

확인 후 `Ctrl-C`로 종료한다.

- [ ] **Step 6: 포트 충돌 시 종료 코드 확인**

한 터미널에서 서버를 띄워 둔 채, 다른 터미널에서:

Run: `uv run --directory plugins/mcp-test/server mcp-test-server; echo "exit=$?"`
Expected: `기동 실패: 127.0.0.1:8765 이(가) 이미 사용 중이다` 와 `exit=1`

- [ ] **Step 7: 커밋**

```bash
git add plugins/mcp-test/server/src/mcp_test_server/app.py \
        plugins/mcp-test/server/src/mcp_test_server/__main__.py \
        plugins/mcp-test/server/tests/test_app.py
git commit -m "feat(server): MCP와 관리 리스너를 한 프로세스에서 함께 기동한다"
```

---

### Task 6: 인수 테스트 — 실제 클라이언트 두 개가 한 프로세스를 공유하는지

이 프로젝트의 요구사항 2·3이 실제로 성립하는지 검증하는 유일한 테스트다.

**Files:**
- Create: `plugins/mcp-test/server/tests/test_acceptance.py`

**Interfaces:**
- Consumes: `build_stack` (Task 5), 도구 이름 `ping`/`whoami`/`sessions` (Task 3)
- Produces: 없음 (테스트 전용)

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_acceptance.py`:

```python
"""실제 포트에 서버를 띄우고 MCP 클라이언트 두 개를 붙인다."""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mcp_test_server.app import build_stack


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def running_server():
    port = free_port()
    mcp_app, admin_app, registry = build_stack(
        host="127.0.0.1", port=port, admin_port=free_port(), stale_after=300.0
    )
    server = uvicorn.Server(
        uvicorn.Config(mcp_app, host="127.0.0.1", port=port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/mcp", registry
    finally:
        server.should_exit = True
        await task


@asynccontextmanager
async def client_for(url: str, instance_id: str, label: str):
    headers = {
        "Authorization": "Bearer alice",
        "X-Client-Instance": instance_id,
        "X-Client-Project": "/tmp/proj",
        "X-Client-Label": label,
    }
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def payload(result) -> dict:
    """도구 결과에서 JSON 본문을 꺼낸다."""
    if result.structuredContent:
        return result.structuredContent
    return json.loads(result.content[0].text)


# lifespan이 안 돌면 initialize가 에러 없이 멈춘다. 매달리지 않고 실패하게 한다.
pytestmark = pytest.mark.timeout(30)


async def test_two_clients_share_one_process():
    async with running_server() as (url, _registry):
        async with client_for(url, "inst-left", "left") as left:
            async with client_for(url, "inst-right", "right") as right:
                left_ping = payload(await left.call_tool("ping", {}))
                right_ping = payload(await right.call_tool("ping", {}))

                # 요구사항 3: 두 클라이언트가 같은 프로세스를 본다.
                # 특정 pid 값이 아니라 '같다'는 것이 요구사항이다.
                assert left_ping["pid"] == right_ping["pid"]

                # 요구사항 2: 서버가 두 세션을 모두 알고 있다
                listing = payload(await left.call_tool("sessions", {}))
                ids = {s["instance_id"] for s in listing["sessions"]}
                assert {"inst-left", "inst-right"} <= ids


async def test_whoami_reflects_the_calling_session():
    async with running_server() as (url, _registry):
        async with client_for(url, "inst-left", "left") as left:
            async with client_for(url, "inst-right", "right") as right:
                assert payload(await left.call_tool("whoami", {}))["label"] == "left"
                assert payload(await right.call_tool("whoami", {}))["label"] == "right"


async def test_echo_round_trips():
    async with running_server() as (url, _):
        async with client_for(url, "inst-left", "left") as left:
            result = await left.call_tool("echo", {"text": "안녕"})
            assert "안녕" in result.content[0].text


async def test_blocked_connection_gets_403_over_the_wire():
    """차단 응답은 원시 HTTP로 확인한다.

    MCP 클라이언트를 거치면 예외 메시지 형식에 의존하게 되고, 그 형식은 SDK
    버전에 따라 달라진다. 우리가 검증할 것은 서버가 403을 낸다는 사실이다.
    """
    headers = {
        "Authorization": "Bearer alice",
        "X-Client-Instance": "inst-left",
        "X-Client-Project": "/tmp/proj",
        "X-Client-Label": "left",
    }
    async with running_server() as (url, registry):
        async with httpx.AsyncClient() as raw:
            before = await raw.post(url, headers=headers, json={})
            assert before.status_code != 403

            registry.block("inst-left")

            after = await raw.post(url, headers=headers, json={})
            assert after.status_code == 403

            registry.unblock("inst-left")

            restored = await raw.post(url, headers=headers, json={})
            assert restored.status_code != 403
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_acceptance.py -v`
Expected: 이 태스크는 새 프로덕션 코드를 만들지 않으므로 통과할 수도 있다. 통과하면 Step 3을 건너뛴다. 실패하면 Step 3의 진단표를 쓴다.

- [ ] **Step 3: 실패를 고친다**

앞선 태스크의 조립이 실제 클라이언트 앞에서 성립하는지 확인하는 것이 이 태스크의 목적이다. 증상별로 아래를 확인한다.

| 증상 | 원인과 확인 방법 |
|---|---|
| **`initialize`에서 멈춘다 (30초 타임아웃)** | `streamable_http_app()`의 lifespan이 `session_manager.run()`을 띄우지 못한 것이다. `uvicorn.Config`에 `AuthMiddleware` 대신 `mcp.streamable_http_app()`을 직접 주고 통과하는지 비교한다. 통과한다면 `AuthMiddleware.__call__`이 `scope["type"] != "http"`을 그대로 하위 앱에 넘기고 있는지 확인한다 — lifespan 스코프를 삼키면 세션 매니저가 시작되지 않는다 |
| 401이 뜬다 | `AuthMiddleware`가 읽는 헤더 이름을 확인한다. Starlette `Headers`는 대소문자를 구분하지 않으므로 정상 구현이면 문제가 없다 |
| `sessions`에 한 세션만 보인다 | `X-Client-Instance`가 클라이언트마다 다른지, 미들웨어가 그 값을 키로 쓰는지 확인한다 |
| 도구 결과 파싱에 실패한다 | `payload()`가 `structuredContent`와 텍스트 본문 양쪽을 다루는지 확인한다 |

- [ ] **Step 4: 전체 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest -v`
Expected: PASS — 전체 통과

- [ ] **Step 5: 커밋**

```bash
git add plugins/mcp-test/server/tests/test_acceptance.py
git commit -m "test(server): 클라이언트 두 개가 한 프로세스를 공유하는지 검증한다"
```

---

### Task 7: 플러그인 파일

플러그인 매니페스트, MCP 등록, 연결 ID 헬퍼, 훅, 슬래시 커맨드를 만든다. 이 태스크가 끝나야 Claude Code가 서버에 붙을 수 있다.

**Files:**
- Create: `plugins/mcp-test/.claude-plugin/plugin.json`
- Create: `plugins/mcp-test/.mcp.json`
- Create: `plugins/mcp-test/scripts/connection-id.sh`
- Create: `plugins/mcp-test/hooks/hooks.json`
- Create: `plugins/mcp-test/hooks/check-server.sh`
- Create: `plugins/mcp-test/commands/server-start.md`
- Create: `plugins/mcp-test/commands/server-status.md`
- Test: `plugins/mcp-test/server/tests/test_plugin_files.py`

**Interfaces:**
- Consumes: 서버가 `--port 8765`에서 `/mcp`를 서비스한다는 사실 (Task 5)
- Produces: 도구의 전체 이름 `mcp__plugin_mcp-test_test-server__<도구>`

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_plugin_files.py`:

```python
"""플러그인 파일이 규격에 맞는지 검사한다.

서버 코드가 아니라 배포 산출물을 검증하는 테스트다. 오타 하나가 설치 후에야
드러나는 것을 막는다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def read_json(relative: str):
    return json.loads((PLUGIN_ROOT / relative).read_text(encoding="utf-8"))


def test_plugin_manifest_declares_both_user_config_options():
    manifest = read_json(".claude-plugin/plugin.json")
    assert manifest["name"] == "mcp-test"
    options = manifest["userConfig"]
    assert options["server_url"]["default"] == "http://127.0.0.1:8765"
    assert options["auth_token"]["sensitive"] is True
    assert options["auth_token"]["required"] is True


def test_mcp_config_uses_http_with_all_three_substitutions():
    server = read_json(".mcp.json")["mcpServers"]["test-server"]
    # url이 있는데 type이 없으면 Claude Code가 설정 오류로 건너뛴다
    assert server["type"] == "http"
    assert server["url"] == "${user_config.server_url}/mcp"
    headers = server["headers"]
    assert headers["Authorization"] == "Bearer ${user_config.auth_token}"
    assert headers["X-Client-Project"] == "${CLAUDE_PROJECT_DIR}"
    assert headers["X-Client-Label"] == "${MCP_TEST_LABEL:-unnamed}"
    assert server["headersHelper"] == "${CLAUDE_PLUGIN_ROOT}/scripts/connection-id.sh"


def test_headers_helper_does_not_reference_user_config():
    # 셸을 거치는 필드는 ${user_config.*}를 거부한다
    helper = (PLUGIN_ROOT / "scripts/connection-id.sh").read_text(encoding="utf-8")
    assert "user_config" not in helper


def test_shell_scripts_are_executable():
    for relative in ("scripts/connection-id.sh", "hooks/check-server.sh"):
        assert os.access(PLUGIN_ROOT / relative, os.X_OK), relative


def test_connection_id_script_emits_distinct_json_ids():
    script = str(PLUGIN_ROOT / "scripts/connection-id.sh")
    first = json.loads(subprocess.run([script], capture_output=True, text=True, check=True).stdout)
    second = json.loads(subprocess.run([script], capture_output=True, text=True, check=True).stdout)
    assert set(first) == {"X-Client-Instance"}
    assert first["X-Client-Instance"]
    assert first["X-Client-Instance"] != second["X-Client-Instance"]


def test_session_start_hook_points_at_the_check_script():
    hooks = read_json("hooks/hooks.json")["hooks"]["SessionStart"]
    commands = [h["command"] for entry in hooks for h in entry["hooks"]]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/check-server.sh" in commands


def test_check_server_script_reads_the_plugin_option_env_var():
    script = (PLUGIN_ROOT / "hooks/check-server.sh").read_text(encoding="utf-8")
    assert "CLAUDE_PLUGIN_OPTION_SERVER_URL" in script


def test_check_server_script_never_blocks_the_session():
    env = {**os.environ, "CLAUDE_PLUGIN_OPTION_SERVER_URL": "http://127.0.0.1:1"}
    result = subprocess.run(
        [str(PLUGIN_ROOT / "hooks/check-server.sh")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0


def test_commands_exist():
    for name in ("server-start.md", "server-status.md"):
        assert (PLUGIN_ROOT / "commands" / name).is_file()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_plugin_files.py -v`
Expected: FAIL — `FileNotFoundError: .../.claude-plugin/plugin.json`

- [ ] **Step 3: 플러그인 매니페스트와 MCP 등록 작성**

`plugins/mcp-test/.claude-plugin/plugin.json`:

```json
{
  "name": "mcp-test",
  "description": "여러 Claude 세션이 하나의 파이썬 프로세스에 붙는 MCP 테스트 서버",
  "version": "0.1.0",
  "author": { "name": "exintueri" },
  "userConfig": {
    "server_url": {
      "type": "string",
      "title": "MCP 서버 주소",
      "description": "테스트 서버의 베이스 URL. 기본값은 로컬 기동 시의 주소",
      "default": "http://127.0.0.1:8765"
    },
    "auth_token": {
      "type": "string",
      "title": "인증 토큰",
      "description": "비어 있지 않으면 통과한다. 이 값이 관리 화면의 세션 식별자로 표시된다",
      "sensitive": true,
      "required": true
    }
  }
}
```

`plugins/mcp-test/.mcp.json`:

```json
{
  "mcpServers": {
    "test-server": {
      "type": "http",
      "url": "${user_config.server_url}/mcp",
      "headers": {
        "Authorization": "Bearer ${user_config.auth_token}",
        "X-Client-Project": "${CLAUDE_PROJECT_DIR}",
        "X-Client-Label": "${MCP_TEST_LABEL:-unnamed}"
      },
      "headersHelper": "${CLAUDE_PLUGIN_ROOT}/scripts/connection-id.sh"
    }
  }
}
```

- [ ] **Step 4: 연결 ID 헬퍼 작성**

`plugins/mcp-test/scripts/connection-id.sh`:

```sh
#!/bin/sh
# headersHelper — Claude Code가 연결마다 한 번(세션 시작과 재연결 시점)
# 실행한다. 여기서 발급한 ID가 그 연결의 모든 요청에 실린다.
#
# ${user_config.*}를 여기에 쓰면 안 된다. 이 명령은 셸을 거치므로
# Claude Code가 치환을 거부하고 서버를 misconfigured로 표시한다.
set -eu

id=$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')
short=$(printf '%s' "$id" | tr -d '-' | cut -c1-12)

printf '{"X-Client-Instance": "%s"}\n' "$short"
```

실행 권한을 준다:

```bash
chmod +x plugins/mcp-test/scripts/connection-id.sh
```

- [ ] **Step 5: 훅 작성**

`plugins/mcp-test/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-server.sh"
          }
        ]
      }
    ]
  }
}
```

`plugins/mcp-test/hooks/check-server.sh`:

```sh
#!/bin/sh
# 플러그인 설정 값을 환경변수로 받는 예시.
#
# 셸에서 실행되는 필드는 ${user_config.*}를 거부한다. 대신 Claude Code가
# 모든 userConfig 값을 훅 프로세스에 CLAUDE_PLUGIN_OPTION_<KEY>로 내려준다.
#
# 생존 확인은 인증 없이 /mcp에 POST해서 401이 오는지 보는 것이다.
# 401은 서버가 살아 있다는 것과 인증이 실제로 걸려 있다는 것을 함께 증명한다.
set -u

url="${CLAUDE_PLUGIN_OPTION_SERVER_URL:-http://127.0.0.1:8765}"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 -X POST "$url/mcp" 2>/dev/null || echo "000")

case "$code" in
  401)
    ;;
  000)
    echo "MCP 테스트 서버($url)가 응답하지 않는다. /mcp-test:server-start 로 띄워라."
    ;;
  *)
    echo "MCP 테스트 서버($url)가 예상 밖의 상태다: HTTP $code (401을 기대했다)."
    ;;
esac

# 훅은 어떤 경우에도 세션을 막지 않는다.
exit 0
```

실행 권한을 준다:

```bash
chmod +x plugins/mcp-test/hooks/check-server.sh
```

- [ ] **Step 6: 슬래시 커맨드 작성**

`plugins/mcp-test/commands/server-start.md`:

```markdown
---
description: MCP 테스트 서버를 기동한다
---

MCP 테스트 서버를 기동한다.

1. 이미 떠 있는지 확인한다. `curl -s -o /dev/null -w '%{http_code}' --max-time 2 -X POST http://127.0.0.1:8765/mcp` 가 `401`을 반환하면 이미 기동된 것이다. 그 사실을 알리고 여기서 멈춘다.
2. 떠 있지 않으면 백그라운드로 기동한다.

   ```bash
   uv run --directory ${CLAUDE_PLUGIN_ROOT}/server mcp-test-server
   ```

3. 기동되면 MCP 엔드포인트(`http://127.0.0.1:8765/mcp`)와 관리 페이지(`http://127.0.0.1:8766/`) 주소를 알린다.
4. 새 세션에서 서버에 붙으려면 `/mcp`로 연결 상태를 확인하라고 안내한다.

포트를 바꾸려면 `--port`와 `--admin-port`를 쓴다. 이 경우 플러그인 설정의 `server_url`도 함께 바꿔야 한다.
```

`plugins/mcp-test/commands/server-status.md`:

```markdown
---
description: MCP 테스트 서버에 붙어 있는 세션을 조회한다
---

관리 포트에서 서버 상태를 조회해 요약한다.

1. `curl -s http://127.0.0.1:8766/api/status` 를 실행한다.
2. 응답이 없으면 서버가 떠 있지 않은 것이다. `/mcp-test:server-start` 를 안내하고 멈춘다.
3. 응답을 받으면 아래를 표로 정리해 보여준다.
   - 서버 pid와 uptime
   - 세션 수
   - 세션별 연결 ID, subject, project, label, 호출 횟수, stale 여부, 차단 여부
4. 세션이 둘 이상이면 모두 같은 pid의 프로세스에 붙어 있다는 점을 함께 짚어 준다.

브라우저로 보려면 `http://127.0.0.1:8766/` 를 열라고 안내한다.
```

- [ ] **Step 7: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_plugin_files.py -v`
Expected: PASS — 9개 통과

- [ ] **Step 8: 커밋**

```bash
git add plugins/mcp-test/.claude-plugin/plugin.json \
        plugins/mcp-test/.mcp.json \
        plugins/mcp-test/scripts/connection-id.sh \
        plugins/mcp-test/hooks/hooks.json \
        plugins/mcp-test/hooks/check-server.sh \
        plugins/mcp-test/commands/server-start.md \
        plugins/mcp-test/commands/server-status.md \
        plugins/mcp-test/server/tests/test_plugin_files.py
git commit -m "feat(plugin): 플러그인 매니페스트와 MCP 등록·훅·커맨드를 만든다"
```

---

### Task 8: 마켓플레이스 카탈로그와 문서

저장소를 마켓플레이스로 만들고, 설치·기동·수동 검증 절차를 문서로 남긴다.

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Modify: `README.md` (현재 21바이트짜리 자리표시자를 전면 교체한다)
- Test: `plugins/mcp-test/server/tests/test_marketplace.py`

**Interfaces:**
- Consumes: 플러그인 이름 `mcp-test`와 경로 `plugins/mcp-test` (Task 7)
- Produces: 없음 (최종 산출물)

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_marketplace.py`:

```python
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_marketplace_lists_the_plugin_with_a_relative_source():
    catalog = json.loads(
        (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    assert catalog["name"] == "basic-mcp-py-server"
    assert catalog["owner"]["name"]

    entries = {p["name"]: p for p in catalog["plugins"]}
    assert "mcp-test" in entries
    source = entries["mcp-test"]["source"]
    # 상대 경로는 ./ 로 시작해야 하고 마켓플레이스 루트 기준으로 해석된다
    assert source == "./plugins/mcp-test"
    assert (REPO_ROOT / source).is_dir()


def test_marketplace_name_is_not_reserved():
    reserved = {
        "claude-code-marketplace",
        "claude-code-plugins",
        "claude-plugins-official",
        "claude-plugins-community",
        "claude-community",
        "anthropic-marketplace",
        "anthropic-plugins",
        "agent-skills",
        "anthropic-agent-skills",
        "knowledge-work-plugins",
        "life-sciences",
        "claude-for-legal",
        "claude-for-financial-services",
        "financial-services-plugins",
        "first-party-plugins",
        "healthcare",
    }
    catalog = json.loads(
        (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    assert catalog["name"] not in reserved


def test_readme_documents_the_install_commands():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "claude plugin marketplace add dev-exintueri/basic-mcp-py-server" in readme
    assert "claude plugin install mcp-test@basic-mcp-py-server" in readme
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest tests/test_marketplace.py -v`
Expected: FAIL — `FileNotFoundError: .../.claude-plugin/marketplace.json`

- [ ] **Step 3: 마켓플레이스 카탈로그 작성**

`.claude-plugin/marketplace.json`:

```json
{
  "name": "basic-mcp-py-server",
  "owner": { "name": "exintueri" },
  "description": "MCP 테스트 서버 플러그인",
  "plugins": [
    {
      "name": "mcp-test",
      "source": "./plugins/mcp-test",
      "description": "여러 Claude 세션이 하나의 파이썬 프로세스에 붙는 MCP 테스트 서버",
      "version": "0.1.0",
      "author": { "name": "exintueri" },
      "keywords": ["mcp", "test", "http"]
    }
  ]
}
```

- [ ] **Step 4: README 작성**

`README.md`를 아래 내용으로 전면 교체한다.

````markdown
# basic-mcp-py-server

여러 Claude Code 세션이 **하나의 파이썬 프로세스**에 MCP로 붙는 테스트 서버다.
이 저장소 자체가 플러그인 마켓플레이스이기도 하다.

설계 근거는 [설계 문서](docs/superpowers/specs/2026-07-25-mcp-test-server-plugin-design.md)에 있다.

## 왜 HTTP인가

stdio 전송은 세션마다 서버 프로세스를 새로 띄운다. 하나의 프로세스를 여러
세션이 공유하려면 HTTP여야 한다.

## 설치

```bash
claude plugin marketplace add dev-exintueri/basic-mcp-py-server
claude plugin install mcp-test@basic-mcp-py-server
```

설치 중 두 가지를 묻는다.

| 설정 | 기본값 | 설명 |
|---|---|---|
| MCP 서버 주소 | `http://127.0.0.1:8765` | 서버를 다른 포트로 띄웠다면 여기도 바꾼다 |
| 인증 토큰 | 없음 (필수) | 비어 있지 않으면 통과한다. 이 값이 관리 화면에 세션 식별자로 표시되므로 `alice` 처럼 알아볼 수 있는 값을 넣으면 편하다 |

## 서버 기동

플러그인 설치와 서버 기동은 별개다. 서버는 독립 프로세스로 직접 띄운다.

```bash
# 저장소에서 (개발 중)
uv run --directory plugins/mcp-test/server mcp-test-server

# 포트 변경
uv run --directory plugins/mcp-test/server mcp-test-server --port 9000 --admin-port 9001
```

Claude Code 안에서는 `/mcp-test:server-start` 로도 띄울 수 있다.

기동하면 두 주소가 열린다.

| | 주소 | 인증 |
|---|---|---|
| MCP | `http://127.0.0.1:8765/mcp` | 필수 |
| 관리 페이지 | `http://127.0.0.1:8766/` | 없음 (루프백 전용) |

관리 페이지의 바인딩 주소는 바꿀 수 없다. 인증이 없는 리스너이기 때문이다.

## 도구

| 도구 | 하는 일 |
|---|---|
| `ping` | 서버 pid, uptime, 세션 수 |
| `echo` | 받은 문자열을 그대로 반환 |
| `whoami` | 이 세션이 서버에 어떻게 보이는지 |
| `sessions` | 붙어 있는 모든 세션 |

권한 규칙에 쓸 전체 이름은 `mcp__plugin_mcp-test_test-server__ping` 형태다.
서버 키만 쓴 `mcp__test-server__*` 는 플러그인 번들 서버에 대해 동작하지 않는다.

## 수동 검증 체크리스트

**같은 디렉토리에서** 터미널 두 개를 띄우는 것이 중요하다. 서로 다른
프로젝트에서 띄우면 프로젝트 경로만으로 구분되어, 연결 ID가 실제로
동작하는지 확인되지 않는다.

- [ ] 터미널 1에서 서버를 띄운다
- [ ] 터미널 2에서 `claude` 실행 후 `ping` 호출 → pid 기록
- [ ] 터미널 3에서 **같은 디렉토리로** `claude` 실행 후 `ping` 호출 → pid가 같은지 확인
- [ ] 둘 중 아무 쪽에서나 `sessions` 호출 → 세션 2개, `X-Client-Instance` 가 서로 다른지 확인
- [ ] 브라우저로 `http://127.0.0.1:8766/` 열기 → 같은 세션 2개가 보이는지 확인
- [ ] 한 세션을 차단 → 그 세션에서 도구를 호출하면 새 연결 ID로 되살아나는지 확인
- [ ] 서버를 끄고 새 `claude` 세션 시작 → `SessionStart` 훅이 기동 안내를 출력하는지 확인

세션에 사람이 읽을 이름을 붙이려면 `MCP_TEST_LABEL` 을 다르게 주고 실행한다.

```bash
MCP_TEST_LABEL=left  claude
MCP_TEST_LABEL=right claude
```

## 개발

```bash
uv run --directory plugins/mcp-test/server pytest -v
```

## 문서

- [설계 문서](docs/superpowers/specs/2026-07-25-mcp-test-server-plugin-design.md)
- [구현 계획](docs/superpowers/plans/2026-07-25-mcp-test-server-plugin.md)
- [Claude Code MCP 공식 문서 사본](docs/claude-base/README.md)
````

- [ ] **Step 5: 테스트가 통과하는지 확인**

Run: `uv run --directory plugins/mcp-test/server pytest -v`
Expected: PASS — 전체 통과

- [ ] **Step 6: 마켓플레이스를 로컬 경로로 실제 등록해 본다**

Run: `claude plugin marketplace add ./`
Expected: 마켓플레이스가 등록되고 `mcp-test` 플러그인이 목록에 보인다.

Run: `claude plugin marketplace list`
Expected: `basic-mcp-py-server` 가 목록에 있다.

문제가 있으면 오류 메시지가 가리키는 파일을 고친다. 확인 후 정리한다.

Run: `claude plugin marketplace remove basic-mcp-py-server`

- [ ] **Step 7: 커밋**

```bash
git add .claude-plugin/marketplace.json README.md \
        plugins/mcp-test/server/tests/test_marketplace.py
git commit -m "feat: 저장소를 플러그인 마켓플레이스로 만들고 사용법을 문서화한다"
```

---

## 완료 기준

전부 만족해야 끝난 것이다.

- [ ] `uv run --directory plugins/mcp-test/server pytest -v` 전체 통과
- [ ] 서로 다른 두 Claude Code 세션이 `ping`에서 **같은 pid**를 본다
- [ ] `sessions`가 두 세션을 모두 보여주고 `X-Client-Instance`가 서로 다르다
- [ ] 브라우저에서 `http://127.0.0.1:8766/` 가 열리고 세션이 보인다
- [ ] 인증 없이 `/mcp`에 POST하면 401이다
- [ ] 관리 포트가 루프백 밖에서 도달 불가하다
- [ ] `claude plugin marketplace add` 로 이 저장소가 등록된다
