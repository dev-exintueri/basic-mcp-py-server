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
