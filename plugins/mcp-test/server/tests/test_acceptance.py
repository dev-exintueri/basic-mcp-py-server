"""실제 포트에 서버를 띄우고 MCP 클라이언트 두 개를 붙인다."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

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


async def _port_ready(host: str, port: int) -> bool:
    """리스닝 소켓이 연결을 받는지 한 번 찔러본다. 실패하면 False."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=0.2
        )
    except OSError:
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


def _terminate_and_reap(proc: subprocess.Popen, log_path: Path) -> str:
    """자식 프로세스를 정리하고 로그 파일에 쌓인 출력을 반환한다.

    실패 진단(진단표: 바인딩 실패, import 오류)이 타임아웃으로 뭉개지지
    않도록, 종료시키면서 stdout/stderr(합쳐서 리다이렉트됨)를 모은다.

    두 번 불러도 안전하다 — 타임아웃 경로에서 한 번, 그 뒤 finally에서 또
    한 번 불릴 수 있다. proc.wait()는 이미 회수된 프로세스에도 즉시
    반환하고(returncode가 캐시돼 있으므로), 로그는 파이프가 아니라 파일에
    쓰게 했으므로 여러 번 읽어도 스트림을 닫아버리는 부작용이 없다.
    """
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    else:
        proc.wait(timeout=5)
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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
        # 바인딩에 실패하면 uvicorn은 태스크 안에서 sys.exit(1)을 부른다.
        # started는 영영 True가 되지 않으므로, 죽었는지 보지 않으면 이 루프가
        # 30초 타임아웃까지 돌면서 진짜 OSError를 가려 버린다.
        if task.done():
            task.result()
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
                # 주의: 이 in-process 버전은 uvicorn이 이 테스트 프로세스 안에서
                # asyncio task로 돌기 때문에 구조적으로 항상 참이다 — 세션 공유가
                # 완전히 깨져 있어도 통과한다. 실제 증명은 별도 OS 프로세스를
                # 띄우는 test_two_real_processes_share_one_server 가 한다.
                assert left_ping["pid"] == right_ping["pid"]

                # 요구사항 2: 서버가 두 세션을 모두 알고 있다
                listing = payload(await left.call_tool("sessions", {}))
                ids = {s["instance_id"] for s in listing["sessions"]}
                assert {"inst-left", "inst-right"} <= ids


async def test_two_real_processes_share_one_server():
    """실제 배포 진입점(`python -m mcp_test_server`)을 별도 OS 프로세스로 띄운다.

    위 test_two_clients_share_one_process 의 pid 비교는 uvicorn이 테스트
    프로세스 안에서 asyncio task로 도는 구조상 항상 참이다. 이 테스트가
    "서로 다른 두 세션이 실제로 별도 프로세스 하나를 공유한다"는 프로젝트의
    핵심 요구사항을 증명하는 유일한 테스트다.
    """
    port = free_port()
    admin_port = free_port()

    # 자식의 stdout/stderr를 파이프가 아니라 파일에 받는다. 파이프는 이
    # 테스트가 살아 있는 동안 비우지 않으므로, 로그가 OS 파이프 버퍼(보통
    # 64KB)를 넘기면 자식이 쓰기에서 블록되고 이 테스트는 읽기를 기다리며
    # 함께 멈추는 잠재적 교착 상태가 된다. 파일은 그런 한도가 없다.
    fd, log_path_str = tempfile.mkstemp(prefix="mcp-test-server-", suffix=".log")
    os.close(fd)
    log_path = Path(log_path_str)
    try:
        with open(log_path, "wb") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "mcp_test_server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--admin-port",
                    str(admin_port),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        try:
            url = f"http://127.0.0.1:{port}/mcp"

            # 포트를 폴링한다 — 고정 sleep이 아니라 자체 데드라인을 둬서,
            # 바인딩 실패나 import 오류가 30초 타임아웃 뒤에 뭉개지지 않고
            # 자기 원인 그대로 드러나게 한다.
            deadline = time.monotonic() + 20.0
            while True:
                if proc.poll() is not None:
                    output = _terminate_and_reap(proc, log_path)
                    pytest.fail(
                        "서버 프로세스가 준비되기 전에 종료됨 "
                        f"(exit={proc.returncode}):\n{output}"
                    )
                if await _port_ready("127.0.0.1", port):
                    break
                if time.monotonic() > deadline:
                    output = _terminate_and_reap(proc, log_path)
                    pytest.fail(f"서버가 20초 안에 포트를 열지 않음:\n{output}")
                await asyncio.sleep(0.05)

            async with client_for(url, "inst-left", "left") as left:
                async with client_for(url, "inst-right", "right") as right:
                    left_ping = payload(await left.call_tool("ping", {}))
                    right_ping = payload(await right.call_tool("ping", {}))

                    # 두 클라이언트가 같은 (별도) 프로세스를 본다
                    assert left_ping["pid"] == right_ping["pid"]
                    # 그 프로세스가 이 테스트 자신이 아니라 진짜 별도 프로세스다
                    assert left_ping["pid"] != os.getpid()

                    listing = payload(await left.call_tool("sessions", {}))
                    ids = {s["instance_id"] for s in listing["sessions"]}
                    assert {"inst-left", "inst-right"} <= ids
        finally:
            _terminate_and_reap(proc, log_path)
    finally:
        log_path.unlink(missing_ok=True)


def test_terminate_and_reap_is_idempotent(tmp_path):
    """`_terminate_and_reap`을 두 번 불러도 안전한지 직접 증명한다.

    실패 진단 경로(타임아웃)에서 한 번 부르고 finally에서 또 한 번 부르는
    구조이므로, 두 번째 호출이 예외를 내거나 캡처한 출력을 잃으면 안 된다.
    """
    log_path = tmp_path / "child.log"
    with open(log_path, "wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", "print('hello')"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    proc.wait(timeout=5)

    first = _terminate_and_reap(proc, log_path)
    second = _terminate_and_reap(proc, log_path)

    assert "hello" in first
    assert second == first


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
