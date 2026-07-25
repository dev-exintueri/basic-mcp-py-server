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


async def _purge_loop(registry: Registry, clock: Callable[[], datetime]) -> None:
    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        registry.purge(clock())


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

    purge = asyncio.create_task(_purge_loop(registry, _utcnow))
    try:
        await asyncio.gather(mcp_server.serve(), admin_server.serve())
    finally:
        purge.cancel()
