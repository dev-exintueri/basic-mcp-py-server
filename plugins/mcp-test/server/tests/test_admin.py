import asyncio
from datetime import datetime, timezone

import httpx
from starlette.responses import JSONResponse

from mcp_test_server.admin import build_admin_app
from mcp_test_server.registry import Registry

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def build_app(registry):
    return build_admin_app(
        registry,
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
    )


def build_client(registry):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)),
        base_url="http://admin",
    )


def make_registry():
    registry = Registry()
    registry.touch(
        instance_id="abc123",
        subject="alice",
        project="/tmp/proj",
        label="left",
        mcp_session_id=None,
        now=T0,
    )
    return registry


async def test_status_returns_server_info_and_sessions():
    async with build_client(make_registry()) as client:
        response = await client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["pid"] > 0
    assert body["mcp_endpoint"] == "http://127.0.0.1:8765/mcp"
    assert body["session_count"] == 1
    assert body["sessions"][0]["instance_id"] == "abc123"


async def test_block_marks_the_session():
    registry = make_registry()
    async with build_client(registry) as client:
        response = await client.post("/api/sessions/abc123/block")
    assert response.status_code == 200
    assert registry.is_blocked("abc123") is True


async def test_unblock_clears_the_flag():
    registry = make_registry()
    registry.block("abc123")
    async with build_client(registry) as client:
        response = await client.post("/api/sessions/abc123/unblock")
    assert response.status_code == 200
    assert registry.is_blocked("abc123") is False


async def test_block_unknown_session_is_404():
    async with build_client(make_registry()) as client:
        response = await client.post("/api/sessions/nope/block")
    assert response.status_code == 404
    assert "error" in response.json()


async def test_index_page_lists_sessions_as_html():
    async with build_client(make_registry()) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "abc123" in response.text
    assert "alice" in response.text


class _ThrowawayGate:
    """이 테스트 전용의 최소 인증 게이트. 제품 코드가 아니다.

    MCP 앱이 AuthMiddleware를 두르는 것과 똑같은 순수 ASGI 형태다. 헤더
    하나가 없으면 401을 돌려주고, 있으면 감싼 앱에 그대로 넘긴다.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            if headers.get(b"x-admin-token") != self.token.encode():
                await JSONResponse({"error": "인증 필요"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


async def test_admin_app_composes_under_an_auth_layer():
    """지금은 인증을 붙이지 않지만, 나중에 붙일 때 구조를 뜯을 필요가 없음을 증명한다.

    관리 앱은 인증이 없다. 그 결정은 유지하되, "나중에 인증을 추가해도
    충돌하는 부분이 없어야 한다"는 조건은 주석이 아니라 테스트로 지킨다.
    build_admin_app 이 돌려주는 앱을 밖에서 ASGI 게이트로 감싸는 것만으로
    모든 경로가 막히고, 통과시키면 그대로 동작한다는 것을 보인다. 즉 미래의
    인증 기능은 serve() 안의 한 줄짜리 래퍼이지 재설계가 아니다.

    이 테스트가 깨진다면 관리 앱이 자기 앞단을 가정하는 무언가를 갖게 된
    것이다 (예: 라우팅을 우회하는 경로, 앱 내부에서만 아는 상태).
    """
    registry = make_registry()
    gate = _ThrowawayGate(build_app(registry), token="s3cret")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gate), base_url="http://admin"
    ) as client:
        # 인증 없이는 페이지도 차단 API도 통과하지 못한다
        assert (await client.get("/")).status_code == 401
        blocked = await client.post("/api/sessions/abc123/block")
        assert blocked.status_code == 401
        # 거부된 요청이 레지스트리에 손대지 않았다
        assert registry.is_blocked("abc123") is False

        # 인증을 통과하면 지금과 똑같이 동작한다
        auth = {"X-Admin-Token": "s3cret"}
        page = await client.get("/", headers=auth)
        assert page.status_code == 200
        assert "abc123" in page.text

        allowed = await client.post("/api/sessions/abc123/block", headers=auth)
        assert allowed.status_code == 200
        assert registry.is_blocked("abc123") is True


async def test_index_page_escapes_session_values():
    registry = Registry()
    registry.touch(
        instance_id="abc123",
        subject="<script>alert(1)</script>",
        project="/tmp/proj",
        label="left",
        mcp_session_id=None,
        now=T0,
    )
    async with build_client(registry) as client:
        response = await client.get("/")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


async def test_page_has_no_meta_refresh_so_sse_survives() -> None:
    """전체 새로고침은 EventSource 연결을 5초마다 끊는다."""
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        page = await client.get("/")
    assert "http-equiv=\"refresh\"" not in page.text


async def test_sessions_fragment_returns_only_the_table() -> None:
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        fragment = await client.get("/fragments/sessions")
    assert fragment.status_code == 200
    assert "abc123" in fragment.text
    assert "<!doctype html>" not in fragment.text.lower()


async def test_status_exposes_the_log_paths(tmp_path) -> None:
    from mcp_test_server.admin import build_admin_app

    log_file = tmp_path / "mcp-test-server.8765.2026-07-25.log"
    log_file.write_text("x", encoding="utf-8")
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        log_file=lambda: log_file,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        body = (await client.get("/api/status")).json()
    assert body["log_file"] == str(log_file)
    assert body["log_dir"] == str(tmp_path)


async def test_status_reports_null_when_file_logging_is_off() -> None:
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        body = (await client.get("/api/status")).json()
    assert body["log_file"] is None
    assert body["log_dir"] is None


async def test_page_backfills_the_tail_of_the_log_file(tmp_path) -> None:
    from mcp_test_server.admin import build_admin_app

    log_file = tmp_path / "mcp-test-server.8765.2026-07-25.log"
    log_file.write_text("첫 줄\n<script>나쁜것</script>\n", encoding="utf-8")
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        log_file=lambda: log_file,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://admin"
    ) as client:
        page = await client.get("/")

    assert "첫 줄" in page.text
    assert "&lt;script&gt;" in page.text          # 이스케이프됐다
    assert "<script>나쁜것</script>" not in page.text


async def test_stream_is_503_when_the_broadcaster_is_off() -> None:
    """브로드캐스터가 없으면 구독을 만들지 않고 503을 돌려준다."""
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        response = await client.get("/api/logs/stream")
    assert response.status_code == 503


def _sse_scope(path: str, headers: dict[str, str] | None = None) -> dict:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "scheme": "http",
        "server": ("admin", 80),
        "client": ("test", 12345),
        "root_path": "",
    }


class _StreamSession:
    """SSE 라우트를 raw ASGI 로 직접 구동한다.

    httpx.ASGITransport(0.28 기준)는 self.app(...) 이 끝까지 돌아야 Response
    를 만든다 — 끝나지 않는 스트림과는 근본적으로 안 맞는다 (별도 확인:
    client.stream() 의 __aenter__ 조차 앱이 완주할 때까지 반환하지 않는다).
    그래서 스트림을 쓰는 테스트만 scope/receive/send 를 직접 만들어 앱을
    백그라운드 태스크로 돌리고, 보낸 메시지를 큐로 받아 발행·연결 종료
    시점을 시험 코드가 직접 조종한다.
    """

    def __init__(self, app, path: str = "/api/logs/stream", headers=None) -> None:
        self.messages: asyncio.Queue[dict] = asyncio.Queue()
        self._disconnect = asyncio.Event()

        async def receive():
            await self._disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            await self.messages.put(message)

        self.task = asyncio.create_task(
            app(_sse_scope(path, headers), receive, send)
        )

    async def _next(self, timeout: float = 5.0) -> dict:
        return await asyncio.wait_for(self.messages.get(), timeout=timeout)

    async def start(self, timeout: float = 5.0) -> dict:
        """http.response.start 메시지를 받는다. 이 시점엔 구독도 이미 끝나 있다 —
        라우트 핸들러가 subscribe() 를 부르고 나서야 StreamingResponse 가
        만들어지고, 그래야 첫 send() 가 나가기 때문이다."""
        message = await self._next(timeout)
        assert message["type"] == "http.response.start"
        return message

    async def body(self, timeout: float = 5.0) -> bytes:
        message = await self._next(timeout)
        assert message["type"] == "http.response.body"
        return message["body"]

    async def aclose(self, timeout: float = 5.0) -> None:
        self._disconnect.set()
        await asyncio.wait_for(self.task, timeout=timeout)


async def test_stream_emits_published_lines() -> None:
    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )

    session = _StreamSession(app)
    try:
        start = await session.start()
        assert start["status"] == 200
        headers = dict(start["headers"])
        assert headers[b"content-type"].startswith(b"text/event-stream")

        broadcaster.publish("한 줄")
        chunk = (await session.body()).decode()
        assert "data: 한 줄" in chunk
    finally:
        await session.aclose()


async def test_stream_splits_multiline_records_into_separate_data_fields() -> None:
    """트레이스백은 여러 줄이다. data: 한 개에 넣으면 SSE 프레이밍이 깨진다."""
    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )

    session = _StreamSession(app)
    try:
        await session.start()
        broadcaster.publish("첫 줄\nTraceback\n  두 번째")
        chunk = (await session.body()).decode()
        assert chunk == "data: 첫 줄\ndata: Traceback\ndata:   두 번째\n\n"
    finally:
        await session.aclose()


async def test_stream_unsubscribes_when_the_client_disconnects() -> None:
    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    app = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )

    session = _StreamSession(app)
    await session.start()
    broadcaster.publish("x")
    await session.body()
    assert broadcaster.subscriber_count == 1

    await session.aclose()
    assert broadcaster.subscriber_count == 0


async def test_gate_blocks_the_log_stream_and_leaks_no_body() -> None:
    """게이트 테스트의 스트림 판. 기존 테스트는 레지스트리 상태만 본다 —
    스트림의 실패 방식은 레지스트리를 건드리지 않고 내용만 새는 것이다.

    토큰 없이 막히는 쪽만 보면 구독 수 0이 "라우트가 아예 없어서" 나온
    값인지 "게이트가 실제로 막아서" 나온 값인지 구분되지 않는다. 그래서
    토큰을 갖춘 쪽도 함께 확인해, 같은 라우트가 인증을 통과하면 실제로
    스트림을 돌려준다는 것까지 증명한다.
    """
    from mcp_test_server.admin import build_admin_app
    from mcp_test_server.logstream import LogBroadcaster

    broadcaster = LogBroadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    inner = build_admin_app(
        make_registry(),
        started_at=T0,
        clock=lambda: T0,
        mcp_endpoint="http://127.0.0.1:8765/mcp",
        broadcaster=broadcaster,
    )
    gate = _ThrowawayGate(inner, token="s3cret")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gate), base_url="http://admin"
    ) as client:
        broadcaster.publish("비밀-한-줄")
        blocked = await client.get("/api/logs/stream")
    assert blocked.status_code == 401
    assert "비밀-한-줄" not in blocked.text
    assert broadcaster.subscriber_count == 0      # 구독조차 만들어지지 않았다

    # 토큰을 갖추면 같은 라우트가 실제로 스트림을 돌려준다 — 위의 0이
    # 라우트가 없어서 나온 값이 아님을 증명한다.
    session = _StreamSession(gate, headers={"X-Admin-Token": "s3cret"})
    try:
        start = await session.start()
        assert start["status"] == 200
        assert broadcaster.subscriber_count == 1
    finally:
        await session.aclose()


async def test_block_is_recorded_in_the_registry_log(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="mcp_test_server.registry")
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        await client.post("/api/sessions/abc123/block")

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.registry"]
    assert lines == ["block instance=abc123"]


async def test_unknown_instance_is_not_recorded(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="mcp_test_server.registry")
    registry = make_registry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(registry)), base_url="http://admin"
    ) as client:
        response = await client.post("/api/sessions/nope/block")

    assert response.status_code == 404
    assert [r for r in caplog.records if r.name == "mcp_test_server.registry"] == []
