"""관리 포트 앱. 127.0.0.1에만 바인딩되며 인증하지 않는다.

인증이 없는 이유는 브라우저가 URL을 여는 것만으로 Authorization 헤더를
붙일 수 없기 때문이다.

그 대가를 정확히 적어 둔다. 루프백 바인딩은 **다른 기계**를 막을 뿐이다.
이 앱이 상대하려는 클라이언트가 바로 같은 기계의 브라우저이므로, 사용자가
연 아무 웹 페이지나 이 포트에 닿을 수 있다.

- 그 페이지가 폼을 자동 제출하면 사용자의 살아 있는 세션을 차단할 수 있다.
  아래 라우트는 Origin도 Sec-Fetch-Site도 보지 않는다.
- DNS 리바인딩을 쓰면 그 페이지가 /api/status 응답을 읽을 수도 있다.
  Host 헤더도 검사하지 않는다.

그렇게 새는 값은 연결 ID, 프로젝트 경로, 서버 pid, 그리고 subject 로
표시되는 토큰이다.

이 상태를 알고도 받아들인다. 로컬 테스트 도구이고 MCP 쪽 인증부터가 비어
있지 않은 토큰이면 전부 통과시키는 수준이므로, 관리 포트만 방어해 봐야
얻는 것이 없다. 나중에 인증을 붙이기로 하면 이 앱을 고칠 필요 없이
serve()에서 ASGI 게이트로 감싸면 된다 — 그것이 가능하다는 것은
tests/test_admin.py 의 test_admin_app_composes_under_an_auth_layer 가
증명한다.
"""

from __future__ import annotations

import html
import os
from collections.abc import Callable
from datetime import datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from .registry import Registry, session_view

_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>MCP 테스트 서버</title>
<style>
body {{ font-family: ui-monospace, monospace; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; }}
.stale {{ color: #888; }}
.blocked {{ background: #fee; }}
.note {{ color: #666; font-size: .9rem; }}
</style>
</head>
<body>
<h1>MCP 테스트 서버</h1>
<p>pid {pid} · uptime {uptime:.0f}s · MCP {endpoint} · 세션 {count}개</p>
<p class="note">차단하면 그 세션은 403을 받고, Claude Code가 headersHelper를
다시 실행해 <b>새 연결 ID로 되살아난다.</b> 레코드가 사라지고 새 줄이
나타나는 것이 정상이다.</p>
<table>
<tr><th>연결 ID</th><th>subject</th><th>project</th><th>label</th>
<th>연결 시각</th><th>마지막 호출</th><th>호출</th><th></th></tr>
{rows}
</table>
</body>
</html>
"""

_ROW = """<tr class="{classes}">
<td>{instance_id}</td><td>{subject}</td><td>{project}</td><td>{label}</td>
<td>{connected_at}</td><td>{last_seen}</td><td>{call_count}</td>
<td><form method="post" action="/api/sessions/{instance_id}/{action}">
<button type="submit">{action_label}</button></form></td>
</tr>
"""


def build_admin_app(
    registry: Registry,
    started_at: datetime,
    clock: Callable[[], datetime],
    mcp_endpoint: str,
) -> Starlette:
    def _snapshot() -> tuple[datetime, list[dict[str, object]]]:
        now = clock()
        return now, [session_view(r, registry, now) for r in registry.all()]

    async def status(request: Request) -> JSONResponse:
        now, views = _snapshot()
        return JSONResponse(
            {
                "pid": os.getpid(),
                "uptime_seconds": (now - started_at).total_seconds(),
                "mcp_endpoint": mcp_endpoint,
                "session_count": len(views),
                "sessions": views,
            }
        )

    async def index(request: Request) -> HTMLResponse:
        now, views = _snapshot()
        rows = "".join(
            _ROW.format(
                classes=" ".join(
                    c for c, on in (("stale", v["stale"]), ("blocked", v["blocked"])) if on
                ),
                instance_id=html.escape(str(v["instance_id"])),
                subject=html.escape(str(v["subject"])),
                project=html.escape(str(v["project"])),
                label=html.escape(str(v["label"])),
                connected_at=html.escape(str(v["connected_at"])),
                last_seen=html.escape(str(v["last_seen"])),
                call_count=v["call_count"],
                action="unblock" if v["blocked"] else "block",
                action_label="차단 해제" if v["blocked"] else "차단",
            )
            for v in views
        )
        return HTMLResponse(
            _PAGE.format(
                pid=os.getpid(),
                uptime=(now - started_at).total_seconds(),
                endpoint=html.escape(mcp_endpoint),
                count=len(views),
                rows=rows,
            )
        )

    def _toggle(action: str) -> Callable[[Request], object]:
        async def handler(request: Request):
            instance_id = request.path_params["instance_id"]
            changed = (
                registry.block(instance_id)
                if action == "block"
                else registry.unblock(instance_id)
            )
            if not changed:
                return JSONResponse(
                    {"error": f"알 수 없는 연결 ID: {instance_id}"}, status_code=404
                )
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/", status_code=303)
            return JSONResponse({"instance_id": instance_id, "action": action})

        return handler

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route(
                "/api/sessions/{instance_id}/block", _toggle("block"), methods=["POST"]
            ),
            Route(
                "/api/sessions/{instance_id}/unblock",
                _toggle("unblock"),
                methods=["POST"],
            ),
        ]
    )
