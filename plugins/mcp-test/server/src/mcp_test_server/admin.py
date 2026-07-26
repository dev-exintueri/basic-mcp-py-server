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

그렇게 새는 값은 연결 ID, 프로젝트 경로, 서버 pid, subject 로 표시되는
토큰, 그리고 /api/logs/stream 과 로그 백필로 나가는 로그 내용이다 — 후자는
범위가 정해져 있지 않다. 무엇이 로그에 찍히느냐에 따라 트레이스백이나
도구 호출 인자가 그대로 담길 수 있다.

이 상태를 알고도 받아들인다. 로컬 테스트 도구이고 MCP 쪽 인증부터가 비어
있지 않은 토큰이면 전부 통과시키는 수준이므로, 관리 포트만 방어해 봐야
얻는 것이 없다. 나중에 인증을 붙이기로 하면 이 앱을 고칠 필요 없이
serve()에서 ASGI 게이트로 감싸면 된다 — 그것이 가능하다는 것은
tests/test_admin.py 의 test_admin_app_composes_under_an_auth_layer 가
증명한다.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from starlette.routing import Route

from .logpaths import tail_lines
from .logstream import LogBroadcaster
from .registry import Registry, session_view

registry_logger = logging.getLogger("mcp_test_server.registry")

# 브라우저가 유휴 연결을 끊지 않게 하는 주석 하트비트의 간격(초).
_HEARTBEAT_SECONDS = 15.0
# 로그 스트림이 종료 시작 여부를 다시 확인하는 주기(초). 하트비트 간격과
# 별개다 — 이 값은 "종료를 얼마나 늦게 알아채도 되는가"만 정한다.
_STOP_POLL_SECONDS = 1.0
# 세션 표를 다시 받아오는 주기(밀리초). 이 폴링 자체가 접근 로그에 한 줄을
# 남기고 그 줄이 다시 아래 로그 패널로 방송되므로, 주기를 짧게 두면 사용자가
# 보고 있는 화면을 자기 소음으로 채운다. 세션 표는 몇 초 늦어도 무방하다.
_SESSION_POLL_MS = 30000

_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>MCP 테스트 서버</title>
<style>
body {{ font-family: ui-monospace, monospace; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; }}
.stale {{ color: #888; }}
.blocked {{ background: #fee; }}
.note {{ color: #666; font-size: .9rem; }}
#log {{ background: #111; color: #ddd; padding: .8rem; height: 24rem;
        overflow-y: scroll; white-space: pre-wrap; margin-top: .5rem; }}
</style>
</head>
<body>
<h1>MCP 테스트 서버</h1>
<div id="sessions">{sessions}</div>

<h2>로그</h2>
<p class="note">{log_note}</p>
<pre id="log">{log_backfill}</pre>

<script>
// 세션 표는 폴링, 로그는 SSE. 용도가 다르므로 연결을 따로 둔다.
setInterval(async () => {{
  try {{
    const html = await (await fetch('/fragments/sessions')).text();
    document.getElementById('sessions').innerHTML = html;
  }} catch (e) {{ /* 서버가 잠깐 없을 수 있다. 다음 주기에 다시 시도한다. */ }}
}}, {session_poll_ms});

const box = document.getElementById('log');
box.scrollTop = box.scrollHeight;
new EventSource('/api/logs/stream').onmessage = (event) => {{
  // 맨 아래를 보고 있을 때만 따라간다. 위로 올려 읽는 중이면 방해하지 않는다.
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent += event.data + '\\n';
  if (atBottom) box.scrollTop = box.scrollHeight;
}};
</script>
</body>
</html>
"""

_SESSIONS = """<p>pid {pid} · uptime {uptime:.0f}s · MCP {endpoint} · 세션 {count}개</p>
<p class="note">차단하면 그 세션은 403을 받고, Claude Code가 headersHelper를
다시 실행해 <b>새 연결 ID로 되살아난다.</b> 레코드가 사라지고 새 줄이
나타나는 것이 정상이다.</p>
<table>
<tr><th>연결 ID</th><th>subject</th><th>project</th><th>label</th>
<th>연결 시각</th><th>마지막 호출</th><th>호출</th><th></th></tr>
{rows}
</table>
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
    broadcaster: LogBroadcaster | None = None,
    log_file: Callable[[], Path | None] = lambda: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> Starlette:
    def _snapshot() -> tuple[datetime, list[dict[str, object]]]:
        now = clock()
        return now, [session_view(r, registry, now) for r in registry.all()]

    def _sessions_html() -> str:
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
        return _SESSIONS.format(
            pid=os.getpid(),
            uptime=(now - started_at).total_seconds(),
            endpoint=html.escape(mcp_endpoint),
            count=len(views),
            rows=rows,
        )

    async def status(request: Request) -> JSONResponse:
        now, views = _snapshot()
        path = log_file()
        return JSONResponse(
            {
                "pid": os.getpid(),
                "uptime_seconds": (now - started_at).total_seconds(),
                "mcp_endpoint": mcp_endpoint,
                "session_count": len(views),
                "sessions": views,
                "log_dir": str(path.parent) if path else None,
                "log_file": str(path) if path else None,
            }
        )

    async def sessions_fragment(request: Request) -> HTMLResponse:
        return HTMLResponse(_sessions_html())

    async def index(request: Request) -> HTMLResponse:
        path = log_file()
        if path is None:
            note = "파일 로깅이 꺼져 있다. 아래는 이 연결 이후의 로그만 보여준다."
            backfill = ""
        else:
            note = f"{html.escape(str(path))} · 최근 200줄"
            backfill = html.escape("\n".join(tail_lines(path)))
        return HTMLResponse(
            _PAGE.format(
                sessions=_sessions_html(),
                log_note=note,
                log_backfill=backfill,
                session_poll_ms=_SESSION_POLL_MS,
            )
        )

    async def log_stream(request: Request) -> StreamingResponse | JSONResponse:
        if broadcaster is None:
            return JSONResponse({"error": "로그 스트림이 꺼져 있다"}, status_code=503)

        queue = broadcaster.subscribe()

        async def events():
            # 큐를 짧은 주기로 깨워서 기다리는 이유는 하트비트가 아니라 종료다.
            # 15초를 통째로 기다리면 그 사이에 시작된 종료를 최대 15초 동안
            # 못 본다. 유휴 시간을 따로 세서, 하트비트 간격은 예전 그대로
            # _HEARTBEAT_SECONDS 를 유지한다.
            idle = 0.0
            try:
                while True:
                    if should_stop():
                        # 여기서 그냥 돌아간다. 이것이 이 파일에서 가장 중요한
                        # 한 줄이다 — 종료가 시작됐을 때 이 제너레이터가 스스로
                        # 끝나지 않으면 uvicorn 이 유예 시간을 다 기다린 뒤
                        # 태스크를 강제 취소하고, 그 CancelledError 가
                        # "Exception in ASGI application" 트레이스백이 되어
                        # 정상 종료마다 로그에 ERROR 를 남긴다. 취소를 삼켜서
                        # 가리는 것이 아니라 취소할 일 자체를 없앤다.
                        return
                    try:
                        line = await asyncio.wait_for(
                            queue.get(), timeout=_STOP_POLL_SECONDS
                        )
                    except asyncio.TimeoutError:
                        idle += _STOP_POLL_SECONDS
                        if idle >= _HEARTBEAT_SECONDS:
                            # 유휴 연결이 끊기지 않게 하는 주석 하트비트다.
                            idle = 0.0
                            yield b": ping\n\n"
                        continue
                    idle = 0.0
                    # 트레이스백은 여러 줄이다. 줄마다 data: 를 붙이지 않으면
                    # SSE 프레이밍이 깨진다.
                    payload = "".join(f"data: {part}\n" for part in line.split("\n"))
                    yield (payload + "\n").encode("utf-8")
            finally:
                broadcaster.unsubscribe(queue)

        return StreamingResponse(events(), media_type="text/event-stream")

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
            registry_logger.info("%s instance=%s", action, instance_id)
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/", status_code=303)
            return JSONResponse({"instance_id": instance_id, "action": action})

        return handler

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route("/fragments/sessions", sessions_fragment),
            Route("/api/logs/stream", log_stream),
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
