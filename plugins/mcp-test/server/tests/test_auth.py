from datetime import datetime, timezone

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from mcp_test_server.auth import UNKNOWN_INSTANCE, AuthMiddleware, read_identity
from mcp_test_server.registry import Registry

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)

FULL_HEADERS = {
    "authorization": "Bearer alice",
    "x-client-instance": "abc123",
    "x-client-project": "/tmp/proj",
    "x-client-label": "left",
}


# --- read_identity ---


def test_read_identity_parses_all_headers():
    identity = read_identity(FULL_HEADERS)
    assert identity is not None
    assert identity.subject == "alice"
    assert identity.instance_id == "abc123"
    assert identity.project == "/tmp/proj"
    assert identity.label == "left"
    assert identity.mcp_session_id is None


def test_read_identity_picks_up_mcp_session_id():
    identity = read_identity({**FULL_HEADERS, "mcp-session-id": "legacy"})
    assert identity.mcp_session_id == "legacy"


@pytest.mark.parametrize(
    "authorization",
    [None, "", "alice", "Bearer", "Bearer ", "Bearer    ", "Bearer \t "],
)
def test_read_identity_rejects_blank_or_malformed_token(authorization):
    headers = dict(FULL_HEADERS)
    if authorization is None:
        del headers["authorization"]
    else:
        headers["authorization"] = authorization
    assert read_identity(headers) is None


def test_read_identity_strips_surrounding_whitespace_from_token():
    identity = read_identity({**FULL_HEADERS, "authorization": "Bearer   alice  "})
    assert identity.subject == "alice"


def test_read_identity_defaults_missing_optional_headers():
    identity = read_identity({"authorization": "Bearer alice"})
    assert identity.instance_id == UNKNOWN_INSTANCE
    assert identity.project == ""
    assert identity.label == "unnamed"


# --- AuthMiddleware ---


def build_client(registry, clock=lambda: T0):
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/mcp", ok, methods=["POST", "DELETE"])])
    app = AuthMiddleware(inner, registry=registry, clock=clock)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_valid_request_passes_and_is_recorded():
    registry = Registry()
    async with build_client(registry) as client:
        response = await client.post("/mcp", headers=FULL_HEADERS)
    assert response.status_code == 200
    record = registry.get("abc123")
    assert record is not None
    assert record.subject == "alice"
    assert record.call_count == 1


async def test_missing_authorization_is_401_with_challenge():
    registry = Registry()
    headers = {k: v for k, v in FULL_HEADERS.items() if k != "authorization"}
    async with build_client(registry) as client:
        response = await client.post("/mcp", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert registry.all() == []


async def test_blank_token_is_401():
    registry = Registry()
    async with build_client(registry) as client:
        response = await client.post(
            "/mcp", headers={**FULL_HEADERS, "authorization": "Bearer    "}
        )
    assert response.status_code == 401


async def test_blocked_instance_gets_403():
    registry = Registry()
    async with build_client(registry) as client:
        await client.post("/mcp", headers=FULL_HEADERS)
        registry.block("abc123")
        response = await client.post("/mcp", headers=FULL_HEADERS)
    assert response.status_code == 403


async def test_missing_instance_header_is_recorded_as_unknown():
    registry = Registry()
    headers = {k: v for k, v in FULL_HEADERS.items() if k != "x-client-instance"}
    async with build_client(registry) as client:
        response = await client.post("/mcp", headers=headers)
    assert response.status_code == 200
    assert registry.get(UNKNOWN_INSTANCE) is not None


async def test_delete_removes_the_record():
    registry = Registry()
    async with build_client(registry) as client:
        await client.post("/mcp", headers=FULL_HEADERS)
        assert registry.get("abc123") is not None
        response = await client.request("DELETE", "/mcp", headers=FULL_HEADERS)
    assert response.status_code == 200
    assert registry.get("abc123") is None


# --- mask_secret / AUTH_SCOPE_KEY ---


def test_mask_secret_is_stable_and_hides_the_token() -> None:
    from mcp_test_server.auth import mask_secret

    assert mask_secret("alice") == "al…(sha256:2bd806c9)"
    assert mask_secret("alice") == mask_secret("alice")
    assert mask_secret("alice") != mask_secret("bob")


def test_mask_secret_handles_short_and_empty_values() -> None:
    from mcp_test_server.auth import mask_secret

    assert mask_secret("") == "(empty)"
    assert mask_secret("a") == "a…(sha256:ca978112)"


async def test_auth_middleware_records_its_decision_in_the_scope() -> None:
    """access.py 가 읽는 계약이다. 한쪽을 바꾸면 양쪽을 바꿔야 한다."""
    from mcp_test_server.auth import AUTH_SCOPE_KEY, AuthMiddleware

    captured: dict[str, object] = {}

    async def inner(scope, receive, send) -> None:
        captured.update(scope.get(AUTH_SCOPE_KEY) or {})

    registry = Registry(stale_after=300.0)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (b"authorization", b"Bearer alice"),
            (b"x-client-instance", b"i1"),
        ],
    }
    await AuthMiddleware(inner, registry=registry, clock=lambda: T0)(scope, None, None)

    assert captured == {"instance": "i1", "subject": "alice", "reason": None}


async def test_new_connection_is_logged_once_with_a_masked_subject(caplog) -> None:
    import logging

    from mcp_test_server.auth import AuthMiddleware

    caplog.set_level(logging.INFO, logger="mcp_test_server.registry")
    registry = Registry(stale_after=300.0)

    async def inner(scope, receive, send) -> None:
        return None

    middleware = AuthMiddleware(inner, registry=registry, clock=lambda: T0)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (b"authorization", b"Bearer alice"),
            (b"x-client-instance", b"i1"),
        ],
    }
    await middleware(dict(scope), None, None)
    await middleware(dict(scope), None, None)      # 두 번째는 새 연결이 아니다

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.registry"]
    assert len(lines) == 1
    assert "instance=i1" in lines[0]
    assert "alice" not in lines[0]
    assert "sha256:" in lines[0]
