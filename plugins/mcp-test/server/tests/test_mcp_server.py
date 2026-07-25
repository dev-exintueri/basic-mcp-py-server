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
