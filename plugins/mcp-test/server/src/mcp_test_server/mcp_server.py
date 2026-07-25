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
