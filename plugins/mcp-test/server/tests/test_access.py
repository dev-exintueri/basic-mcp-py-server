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

    records = [r for r in caplog.records if r.name == "mcp_test_server.http"]
    assert len(records) == 1                   # 401 경로처럼 두 줄이 나오면 안 된다
    assert records[0].levelno == logging.INFO
    lines = [r.getMessage() for r in records]
    assert "POST /mcp 200" in lines[0]
    assert "dur_ms=" in lines[0]
    assert "instance=i1" in lines[0]
    assert "alice" not in lines[0]             # 평문 토큰이 새면 안 된다
    assert "sha256:" in lines[0]


async def test_control_characters_in_the_path_cannot_forge_a_log_line(caplog) -> None:
    """경로에 넣은 CR/LF 로 로그 줄을 위조하거나 숨길 수 있으면 안 된다.

    httpx 를 거치면 URL 정규화가 제어 문자를 먼저 없애 버리므로, 미들웨어를
    직접 부른다. 이 줄이 그대로 나가면 두 가지가 가능해진다: \\n 은 진짜와
    구별되지 않는 가짜 줄을 만들고(위조), \\r 은 SSE 프레이밍(줄 나누기가
    \\n 기준이다)을 깨서 그 줄을 관리 화면에서 통째로 지운다(은폐).
    """
    caplog.set_level(logging.INFO, logger="mcp_test_server.http")

    async def inner(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def sink(message) -> None:
        return None

    forged = "/mcp\n2026-07-25T00:00:00Z ERROR app 가짜\r숨김"
    await AccessLogMiddleware(inner)(
        {"type": "http", "method": "GET", "path": forged}, None, sink
    )

    lines = http_lines(caplog)
    assert len(lines) == 1
    assert "\n" not in lines[0]
    assert "\r" not in lines[0]
    assert "\\n" in lines[0]
    assert "\\r" in lines[0]


async def test_lifespan_scope_passes_through_untouched(caplog) -> None:
    """이 규칙을 어기면 인수 테스트 전부가 멈춘다."""
    caplog.set_level(logging.INFO, logger="mcp_test_server.http")
    seen: list[object] = []

    async def inner(scope, receive, send) -> None:
        seen.append((scope["type"], send))

    sentinel = object()
    await AccessLogMiddleware(inner)({"type": "lifespan"}, None, sentinel)

    assert seen == [("lifespan", sentinel)]     # send 를 감싸지 않고 그대로 넘긴다
    assert http_lines(caplog) == []             # lifespan 은 접근 로그를 남기지 않는다
