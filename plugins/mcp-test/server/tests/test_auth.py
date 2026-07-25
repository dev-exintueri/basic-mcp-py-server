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
