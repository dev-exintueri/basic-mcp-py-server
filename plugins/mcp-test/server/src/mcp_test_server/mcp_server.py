"""FastMCP 인스턴스와 노출 도구 4개.

## 응용할 때

**바꿔도 되는 것.** 도구를 더하고 빼는 곳은 `build_mcp()` 안이다. 함수를
쓰고 데코레이터 두 개를 얹으면 끝이다. `FastMCP("mcp-test-server")` 의
이름은 이 프로세스 안에서만 쓰인다 — 로그 파일명(`logpaths` 의
`LOG_GLOB`)이나 플러그인 ID 와 연결되지 않으므로 자유롭게 바꾼다.

**깨면 안 되는 것.** `@mcp.tool()` 이 위, `@_logged` 가 아래여야 한다.
FastMCP 의 `tool()` 은 함수를 등록한 뒤 **받은 함수를 그대로 돌려주므로**,
순서를 뒤집으면 서버에 등록되는 것은 원본이고 `_logged` 가 감싼 것은
아무도 부르지 않는 사본이 된다. 도구는 멀쩡히 동작하고 호출 로그만
사라진다 — 오류는 나지 않는다.
"""

from __future__ import annotations

import functools
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime

from mcp.server.fastmcp import Context, FastMCP

from .auth import UNKNOWN_INSTANCE, read_identity
from .registry import Registry, session_view

logger = logging.getLogger("mcp_test_server.call")


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


def build_mcp(
    registry: Registry,
    started_at: datetime,
    clock: Callable[[], datetime],
) -> FastMCP:
    mcp = FastMCP("mcp-test-server")

    @mcp.tool()
    @_logged
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
    @_logged
    def echo(text: str) -> str:
        """받은 문자열을 그대로 돌려준다."""
        return text

    @mcp.tool()
    @_logged
    def whoami(ctx: Context) -> dict[str, object]:
        """이 세션이 서버에 어떻게 보이는지 반환한다."""
        instance_id = _instance_id_of(ctx)
        record = registry.get(instance_id)
        if record is None:
            return {"instance_id": instance_id, "known": False}
        return {"known": True, **session_view(record, registry, clock())}

    @mcp.tool()
    @_logged
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
