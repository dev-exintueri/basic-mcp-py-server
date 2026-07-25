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
