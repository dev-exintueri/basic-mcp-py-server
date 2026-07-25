"""인증·차단 미들웨어와 요청 신원 파싱.

미들웨어는 순수 ASGI다. BaseHTTPMiddleware를 쓰지 않는 이유는 응답을 감싸지
않기 위해서다. 요청 헤더만 읽고 응답에는 손대지 않으므로 스트리밍 응답과
얽히지 않는다.

X-Client-Instance 는 클라이언트가 스스로 주장하는 값이고 검증하지 않는다.
sessions 도구가 모든 연결 ID를 모든 세션에 공개하므로, 비어 있지 않은
토큰만 있으면 누구나 남의 ID로 DELETE 를 보내 레코드를 지우거나 같은 ID로
호출해 그 세션의 subject/project/label 을 덮어쓸 수 있다. 피해는 제한적이고
(다음 요청에서 레코드가 다시 생긴다) 이 설계에 내재한 성질이므로 막지
않는다. 다만 사실로 남겨 둔다.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .registry import Registry

registry_logger = logging.getLogger("mcp_test_server.registry")

UNKNOWN_INSTANCE = "unknown"
_BEARER_PREFIX = "bearer "

# access.py 가 읽는 스코프 키. 스키마는 이 모듈이 정의한다.
#   {"instance": str | None, "subject": str | None, "reason": str | None}
AUTH_SCOPE_KEY = "mcp_test_auth"


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


def mask_secret(value: str) -> str:
    """토큰을 로그에 적을 수 있는 형태로 바꾼다.

    같은 입력은 항상 같은 출력이므로 "이 두 요청은 같은 사람"을 추적할 수
    있다. 앞 두 글자를 남기는 것은 별명을 쓴 경우 사람이 알아보게 하려는
    것이다.

    마스킹은 기록 시점에 한다. 포매터가 정규식으로 훑는 방식은 새 필드가
    생길 때마다 조용히 샌다.
    """
    if not value:
        return "(empty)"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[:2]}…(sha256:{digest})"


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
            scope[AUTH_SCOPE_KEY] = {
                "instance": None,
                "subject": None,
                "reason": "blank-token",
            }
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
            scope[AUTH_SCOPE_KEY] = {
                "instance": identity.instance_id,
                "subject": identity.subject,
                "reason": "blocked",
            }
            await self._reject(
                scope,
                receive,
                send,
                status=403,
                detail=f"연결 {identity.instance_id} 이(가) 관리 화면에서 차단되었다",
            )
            return

        scope[AUTH_SCOPE_KEY] = {
            "instance": identity.instance_id,
            "subject": identity.subject,
            "reason": None,
        }

        if self.registry.get(identity.instance_id) is None:
            # 처음 보는 연결이다. touch 하면 레코드가 생겨 버리므로 그 전에 본다.
            registry_logger.info(
                "connected instance=%s subject=%s label=%s",
                identity.instance_id,
                mask_secret(identity.subject),
                identity.label,
            )

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
