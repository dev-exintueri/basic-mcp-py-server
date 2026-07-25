"""실제 포트에 서버를 띄우고 MCP 클라이언트 두 개를 붙인다."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
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


async def test_crash_leaves_a_traceback_in_the_log_file(tmp_path) -> None:
    """SIGTERM 으로 죽이는 테스트는 아무것도 증명하지 못한다.

    terminate() 는 SIGTERM 이고 파이썬은 이를 기본적으로 잡지 않는다.
    프로세스는 finally 도 atexit 도 실행하지 않고 즉시 끝나므로, 그렇게
    죽인 뒤 로그를 확인하는 테스트는 통과해도 flush 가 동작한다는 뜻이
    아니다. 대신 진짜 미처리 예외로 죽인다.

    이 테스트가 실제로 지키는 것은 __main__.main() 의
    `except BaseException: logger.exception(...)` 한 줄이다 — 그 줄을 지우면
    이 테스트는 FAIL한다(직접 지우고 확인했다). 반대로 `finally:
    logging.shutdown()`과 `atexit.register(logging.shutdown)`을 **둘 다**
    지워도 이 테스트는 여전히 PASS한다: stdlib logging.StreamHandler.emit()이
    레코드마다 self.flush()를 부르므로, 프로세스가 정리 없이 죽어도 이미 쓴
    줄은 파일에 남아 있다. 즉 shutdown/atexit 경로에는 이 테스트로 확인되지
    않는 부분이 남아 있다 — 예를 들어 파일 디스크립터를 명시적으로 닫는
    것 자체는 여기서 검증되지 않는다.
    """
    port = free_port()
    child = (
        "import sys\n"
        "import mcp_test_server.app as app\n"
        "import mcp_test_server.__main__ as m\n"
        "async def boom(**kwargs):\n"
        "    raise RuntimeError('deliberate-crash-marker')\n"
        # __main__ 이 from .app import serve 로 이름을 끌어왔으므로 양쪽
        # 모듈 전역을 모두 바꿔야 한다. 한쪽만 바꾸면 패치가 먹지 않고
        # 서버가 정상 기동해 이 테스트가 멈춘다.
        "app.serve = boom\n"
        "m.serve = boom\n"
        "sys.exit(m.main(['--log-dir', sys.argv[1], '--port', sys.argv[2]]))\n"
    )

    proc = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), str(port)],
        capture_output=True,
        timeout=60,
    )

    assert proc.returncode != 0, proc.stderr.decode(errors="replace")

    files = list(tmp_path.glob("mcp-test-server.*.log"))
    assert files, f"로그 파일이 없다. stderr={proc.stderr.decode(errors='replace')}"
    text = files[0].read_text(encoding="utf-8", errors="replace")
    assert "deliberate-crash-marker" in text
    assert "Traceback" in text


@pytest.mark.timeout(90)
async def test_ctrl_c_exits_even_with_an_open_log_stream(tmp_path) -> None:
    """관리 화면을 열어 둔 채로도 Ctrl-C 가 먹는지 본다.

    이 기능이 의도한 사용법이 곧 이 버그의 재현 절차다 — 로그를 보려고
    관리 페이지를 띄워 두면 /api/logs/stream 이 SSE 로 계속 열려 있다.
    uvicorn 은 timeout_graceful_shutdown 이 없으면 그 연결이 스스로 닫히기를
    무한정 기다리므로 프로세스가 영영 끝나지 않는다. build_servers 에서 그
    설정을 빼고 돌리면 이 테스트는 아래 wait 에서 시간 초과로 FAIL 한다
    (실제로 빼고 확인했다).

    SIGTERM 이 아니라 SIGINT 다. 확인하려는 것이 바로 Ctrl-C 이고, 종료
    경로도 서로 다르다. returncode 는 보지 않는다 — KeyboardInterrupt 가
    밖으로 나오는지는 uvicorn 의 시그널 핸들러 설치 여부에 달렸고 이 테스트가
    지키려는 성질이 아니다. 확인할 것은 오직 "끝난다"이다.

    스트림은 헤더가 도착할 때까지 실제로 열어 둔다. 요청만 보내고 마는
    방식은 연결이 정말 살아 있었는지 증명하지 못한다.
    """
    port = free_port()
    admin_port = free_port()

    fd, out_path_str = tempfile.mkstemp(prefix="mcp-test-sigint-", suffix=".log")
    os.close(fd)
    out_path = Path(out_path_str)
    try:
        with open(out_path, "wb") as out_file:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "mcp_test_server",
                    "--host", "127.0.0.1",
                    "--port", str(port),
                    "--admin-port", str(admin_port),
                    "--log-dir", str(tmp_path),
                ],
                stdout=out_file,
                stderr=subprocess.STDOUT,
            )
        try:
            # SSE 는 관리 리스너에 있다. MCP 포트를 기다리면 엉뚱한 것을 본다.
            deadline = time.monotonic() + 20.0
            while True:
                if proc.poll() is not None:
                    output = _terminate_and_reap(proc, out_path)
                    pytest.fail(f"서버가 죽었다:\n{output}")
                if await _port_ready("127.0.0.1", admin_port):
                    break
                if time.monotonic() > deadline:
                    output = _terminate_and_reap(proc, out_path)
                    pytest.fail(f"관리 리스너가 뜨지 않았다:\n{output}")
                await asyncio.sleep(0.05)

            async with httpx.AsyncClient() as client:
                stream = client.stream(
                    "GET", f"http://127.0.0.1:{admin_port}/api/logs/stream"
                )
                response = await stream.__aenter__()
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]

                started = time.monotonic()
                proc.send_signal(signal.SIGINT)
                try:
                    await asyncio.to_thread(proc.wait, 20)
                except subprocess.TimeoutExpired:
                    pytest.fail(
                        "SSE 연결을 열어 둔 채 SIGINT 를 보냈더니 20초 안에 "
                        "종료하지 않았다. timeout_graceful_shutdown 이 빠졌다."
                    )
                elapsed = time.monotonic() - started

                # 종료 중에 본문이 끊기는 것은 정상이다. 그 예외가 이 테스트를
                # 실패로 둔갑시키지 않게 한다.
                with contextlib.suppress(Exception):
                    await stream.__aexit__(None, None, None)

            # 유예 시간(3초)에 정리 시간을 더한 값. 무한 대기와는 자릿수가 다르다.
            assert elapsed < 15.0, f"종료에 {elapsed:.1f}초 걸렸다"
        finally:
            _terminate_and_reap(proc, out_path)
    finally:
        out_path.unlink(missing_ok=True)


async def test_server_starts_even_when_the_log_directory_is_unusable(tmp_path) -> None:
    """로그 디렉토리 때문에 테스트 서버가 뜨지 않는 것은 거꾸로 간 것이다."""
    blocker = tmp_path / "blocked"
    blocker.write_text("파일이라 하위 디렉토리를 만들 수 없다", encoding="utf-8")

    port = free_port()
    admin_port = free_port()
    fd, log_path_str = tempfile.mkstemp(prefix="mcp-test-unusable-", suffix=".log")
    os.close(fd)
    log_path = Path(log_path_str)
    try:
        with open(log_path, "wb") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "mcp_test_server",
                    "--host", "127.0.0.1",
                    "--port", str(port),
                    "--admin-port", str(admin_port),
                    "--log-dir", str(blocker / "logs"),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        try:
            deadline = time.monotonic() + 20.0
            while True:
                if proc.poll() is not None:
                    output = _terminate_and_reap(proc, log_path)
                    pytest.fail(f"서버가 죽었다:\n{output}")
                if await _port_ready("127.0.0.1", port):
                    break
                if time.monotonic() > deadline:
                    output = _terminate_and_reap(proc, log_path)
                    pytest.fail(f"서버가 뜨지 않았다:\n{output}")
                await asyncio.sleep(0.1)

            async with client_for(
                f"http://127.0.0.1:{port}/mcp", "inst-nolog", "nolog"
            ) as session:
                assert payload(await session.call_tool("ping", {}))["pid"] > 0
        finally:
            _terminate_and_reap(proc, log_path)
    finally:
        log_path.unlink(missing_ok=True)
