import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from mcp_test_server.__main__ import parse_args
from mcp_test_server import app as app_module
from mcp_test_server.app import (
    ADMIN_HOST,
    DEFAULTS,
    PortInUse,
    build_stack,
    ensure_port_free,
)
from mcp_test_server.registry import Registry

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


async def test_purge_loop_uses_the_injected_clock(monkeypatch):
    """purge_loop이 실제 시각이 아니라 주어진 clock()을 쓰는지 확인한다.

    레코드의 last_seen은 실제 현재 시각으로 남긴다. purge_after(60초)를
    넘기려면 clock()이 그로부터 120초 뒤인 미래를 돌려줘야 한다. 만약
    _purge_loop이 다시 내부에서 _utcnow()를 부르도록 되돌아가면, 실제
    시각은 last_seen과 거의 같아 purge_after를 넘지 않으므로 레코드가
    지워지지 않고 아래 대기가 타임아웃으로 실패한다.
    """
    monkeypatch.setattr(app_module, "_PURGE_INTERVAL_SECONDS", 0.01)

    registry = Registry(stale_after=300.0, purge_after=60.0)
    real_now = datetime.now(timezone.utc)
    registry.touch(
        instance_id="i1",
        subject="alice",
        project="proj",
        label="label",
        mcp_session_id=None,
        now=real_now,
    )
    far_future = real_now + timedelta(seconds=120)

    task = asyncio.create_task(
        app_module._purge_loop(registry, lambda: far_future)
    )
    try:

        async def wait_for_purge() -> None:
            while registry.all():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_purge(), timeout=1.0)
    finally:
        task.cancel()

    assert registry.all() == []
