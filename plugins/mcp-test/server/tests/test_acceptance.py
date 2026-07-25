"""실제 포트에 서버를 띄우고 MCP 클라이언트 두 개를 붙인다."""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mcp_test_server.app import build_stack


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def running_server():
    port = free_port()
    mcp_app, admin_app, registry = build_stack(
        host="127.0.0.1", port=port, admin_port=free_port(), stale_after=300.0
    )
    server = uvicorn.Server(
        uvicorn.Config(mcp_app, host="127.0.0.1", port=port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/mcp", registry
    finally:
        server.should_exit = True
        await task


@asynccontextmanager
async def client_for(url: str, instance_id: str, label: str):
    headers = {
        "Authorization": "Bearer alice",
        "X-Client-Instance": instance_id,
        "X-Client-Project": "/tmp/proj",
        "X-Client-Label": label,
    }
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def payload(result) -> dict:
    """도구 결과에서 JSON 본문을 꺼낸다."""
    if result.structuredContent:
        return result.structuredContent
    return json.loads(result.content[0].text)


# lifespan이 안 돌면 initialize가 에러 없이 멈춘다. 매달리지 않고 실패하게 한다.
pytestmark = pytest.mark.timeout(30)


async def test_two_clients_share_one_process():
    async with running_server() as (url, _registry):
        async with client_for(url, "inst-left", "left") as left:
            async with client_for(url, "inst-right", "right") as right:
                left_ping = payload(await left.call_tool("ping", {}))
                right_ping = payload(await right.call_tool("ping", {}))

                # 요구사항 3: 두 클라이언트가 같은 프로세스를 본다.
                # 특정 pid 값이 아니라 '같다'는 것이 요구사항이다.
                assert left_ping["pid"] == right_ping["pid"]

                # 요구사항 2: 서버가 두 세션을 모두 알고 있다
                listing = payload(await left.call_tool("sessions", {}))
                ids = {s["instance_id"] for s in listing["sessions"]}
                assert {"inst-left", "inst-right"} <= ids


async def test_whoami_reflects_the_calling_session():
    async with running_server() as (url, _registry):
        async with client_for(url, "inst-left", "left") as left:
            async with client_for(url, "inst-right", "right") as right:
                assert payload(await left.call_tool("whoami", {}))["label"] == "left"
                assert payload(await right.call_tool("whoami", {}))["label"] == "right"


async def test_echo_round_trips():
    async with running_server() as (url, _):
        async with client_for(url, "inst-left", "left") as left:
            result = await left.call_tool("echo", {"text": "안녕"})
            assert "안녕" in result.content[0].text


async def test_blocked_connection_gets_403_over_the_wire():
    """차단 응답은 원시 HTTP로 확인한다.

    MCP 클라이언트를 거치면 예외 메시지 형식에 의존하게 되고, 그 형식은 SDK
    버전에 따라 달라진다. 우리가 검증할 것은 서버가 403을 낸다는 사실이다.
    """
    headers = {
        "Authorization": "Bearer alice",
        "X-Client-Instance": "inst-left",
        "X-Client-Project": "/tmp/proj",
        "X-Client-Label": "left",
    }
    async with running_server() as (url, registry):
        async with httpx.AsyncClient() as raw:
            before = await raw.post(url, headers=headers, json={})
            assert before.status_code != 403

            registry.block("inst-left")

            after = await raw.post(url, headers=headers, json={})
            assert after.status_code == 403

            registry.unblock("inst-left")

            restored = await raw.post(url, headers=headers, json={})
            assert restored.status_code != 403
