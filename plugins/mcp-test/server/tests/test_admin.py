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
