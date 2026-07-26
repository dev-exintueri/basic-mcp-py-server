"""접근 로그 미들웨어.

AuthMiddleware **바깥**에 선다. 401/403 분기는 응답을 보내고 즉시 return
하므로, 그 안쪽에서 상태 코드를 가로채면 거부된 요청이 로그에 아예 남지
않는다 — 그런데 이 서버에서 가장 보고 싶은 줄이 그것이다. 바깥에 서면
거부 응답도 우리가 넘겨준 send 래퍼를 지나간다.

두 앱(MCP, 관리)에 모두 붙여 같은 형식의 접근 로그를 갖게 한다.

## 응용할 때

포크해도 대개 그대로 둔다. 고친다면 `_log()` 가 어떤 필드를 남기는지
정도다.

**깨면 안 되는 것.**

- 이 미들웨어는 `AuthMiddleware` 바깥에 선다 (`app` 의 `build_stack()`).
  안으로 옮기면 거부된 요청이 로그에 남지 않는다.
- 캐리지 리턴과 줄바꿈 이스케이프는 조립이 끝난 한 줄에 한 번 건다.
  필드마다 거는 방식으로 바꾸면 새 필드가 생길 때 조용히 샌다.
- 로그는 응답이 **시작**될 때 남긴다. 완료로 옮기면 SSE 같은 장수 연결이
  끊길 때까지 아무 줄도 남지 않는다.
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

        # 줄바꿈을 이스케이프한 뒤에 넘긴다. path 와 instance 는 클라이언트가
        # 정하는 값이고 마스킹도 걸리지 않는다. 날것으로 두면 요청 하나로
        # 진짜와 구별되지 않는 로그 줄을 만들어 넣을 수 있고(위조), CR 은 그보다
        # 나쁘다 — SSE 프레이밍은 \n 만 나누므로 \r 이 든 줄은 관리 화면에서
        # 통째로 사라진다(은폐). 토큰 없이도 되는 일이라 401 로 거부된 요청에도
        # 해당한다. 조립이 끝난 줄에 한 번만 걸어 어느 필드로 들어오든 막는다.
        line = " ".join(parts).replace("\r", "\\r").replace("\n", "\\n")

        level = logging.WARNING if status >= 400 else logging.INFO
        logger.log(level, line)
