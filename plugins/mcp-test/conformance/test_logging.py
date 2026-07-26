"""슬라이스 3 — 로그 줄과 파일의 계약.

카테고리로 필터링해서 우리 줄을 찾는다. 파이썬 쪽에는 uvicorn 의 error 와
파이썬 MCP SDK 의 streamable_http_manager, transport_security 가 섞이므로,
"모르는 카테고리가 있으면 실패" 로 쓰면 안 된다.
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from conftest import HEADERS, free_port

LINE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) "
    r"(?P<level>INFO |WARN |ERROR) "
    r"(?P<category>\S+)\s+"
    r"(?P<message>.*)$"
)

OUR_CATEGORIES = {"app", "http", "registry", "call"}


def our_lines(text: str, category: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        match = LINE.match(raw)
        if match and match.group("category") == category:
            out.append(match.group("message"))
    return out


def wait_for(handle, category: str, pattern: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in our_lines(handle.log_text(), category):
            if re.search(pattern, message):
                return message
        time.sleep(0.2)
    raise AssertionError(
        f"{category} 카테고리에서 {pattern!r} 을 찾지 못했다.\n로그:\n{handle.log_text()}"
    )


def test_log_file_is_named_by_port_and_date(server) -> None:
    files = list(server.log_dir.glob("mcp-test-server.*.log"))
    assert len(files) == 1, files
    assert re.fullmatch(
        rf"mcp-test-server\.{server.port}\.\d{{4}}-\d{{2}}-\d{{2}}\.log", files[0].name
    )


def test_startup_line_is_written_under_app(server) -> None:
    wait_for(server, "app", r"서버 기동")


def test_rejected_request_is_logged_with_reason(server) -> None:
    httpx.post(server.mcp_url, timeout=5)
    message = wait_for(server, "http", r"POST /mcp 401")
    assert "reason=blank-token" in message
    assert re.search(r"dur_ms=\d+", message)


def test_rejected_request_is_warn_level(server) -> None:
    httpx.post(server.mcp_url, timeout=5)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for raw in server.log_text().splitlines():
            match = LINE.match(raw)
            if match and match.group("category") == "http" and "401" in match.group("message"):
                assert match.group("level") == "WARN "
                return
        time.sleep(0.2)
    raise AssertionError(f"401 줄을 찾지 못했다:\n{server.log_text()}")


def test_token_is_masked_in_the_connected_line(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()

    asyncio.run(run())
    message = wait_for(server, "registry", r"^connected ")
    # 앞 두 글자 + U+2026 + sha256 앞 8자리. 'alice' 의 값이다.
    assert "subject=al…(sha256:2bd806c9)" in message
    assert "alice" not in message


def test_tool_call_is_logged_under_call(server) -> None:
    # ping 이 아니라 whoami 를 부른다. ping() 은 ctx: Context 인자를 받지
    # 않으므로 mcp_server._logged 의 instance = _instance_id_of(ctx) 분기가
    # 걸리지 않고 로그가 항상 instance=unknown 으로 남는다(실측: Task 9).
    # whoami(ctx: Context) 는 실제로 ctx 를 받아 연결 ID를 로그에 남긴다.
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                await session.call_tool("whoami", {})

    asyncio.run(run())
    message = wait_for(server, "call", r"tool=whoami")
    assert f"instance={HEADERS['X-Client-Instance']}" in message
    assert message.endswith(" ok")


def test_control_characters_in_the_path_cannot_forge_a_log_line(server) -> None:
    """경로는 클라이언트가 정하고 마스킹도 걸리지 않는다.

    날것으로 남기면 요청 하나로 진짜와 구별되지 않는 줄을 만들어 넣을 수
    있고(위조), 캐리지 리턴은 그보다 나쁘다 — SSE 프레이밍은 줄바꿈만
    나누므로 캐리지 리턴이 든 줄은 관리 화면에서 통째로 사라진다(은폐).
    """
    httpx.request("POST", f"{server.admin_url}/api/status%0d%0aFORGED", timeout=5)
    text = server.log_text()
    # splitlines() 로 쪼갠 뒤에 검사하지 않는다. 파이썬의 splitlines() 는
    # 캐리지 리턴에서도 쪼개므로 어떤 원소에도 그것이 남지 않고, 단언이
    # 무조건 통과한다. 쪼개지 않은 원문을 본다.
    assert "\r" not in text

    # 줄 수도 본다. 위조가 성공하면 우리 카테고리 줄이 하나 늘어난다.
    forged = [
        raw for raw in text.split("\n")
        if (m := LINE.match(raw)) and m.group("category") in OUR_CATEGORIES and "FORGED" in raw
        and not m.group("message").startswith("POST ")
    ]
    assert forged == [], f"위조된 줄이 생겼다: {forged}"


def test_status_reports_the_log_file(server) -> None:
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert payload["log_dir"] == str(server.log_dir)
    assert payload["log_file"].endswith(".log")


def test_log_stream_emits_new_lines(server) -> None:
    """SSE 스트림에 새 줄이 실시간으로 붙는지 본다."""
    with httpx.stream(
        "GET", f"{server.admin_url}/api/logs/stream", timeout=15
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        httpx.post(server.mcp_url, timeout=5)  # 401 줄 하나를 만든다
        for line in response.iter_lines():
            if line.startswith("data: ") and "401" in line:
                return
    raise AssertionError("스트림에서 401 줄을 받지 못했다")


def test_access_log_records_the_sse_connection_immediately(server) -> None:
    """SSE 는 끝나지 않는다. 완료 시점에 남기면 이 줄이 영영 안 생긴다."""
    with httpx.stream("GET", f"{server.admin_url}/api/logs/stream", timeout=15) as response:
        assert response.status_code == 200
        wait_for(server, "http", r"GET /api/logs/stream 200")


def test_env_var_sets_the_log_dir(spawn, tmp_path) -> None:
    target = tmp_path / "from-env"
    target.mkdir()
    port, admin_port = free_port(), free_port()
    proc, _ = spawn(
        ["--port", str(port), "--admin-port", str(admin_port)],
        {"MCP_TEST_LOG_DIR": str(target)},
    )
    assert list(target.glob("mcp-test-server.*.log")), "환경 변수의 디렉토리에 쓰지 않았다"


def test_flag_beats_the_env_var(spawn, tmp_path) -> None:
    from_env = tmp_path / "env"
    from_flag = tmp_path / "flag"
    from_env.mkdir()
    from_flag.mkdir()
    port, admin_port = free_port(), free_port()
    spawn(
        ["--port", str(port), "--admin-port", str(admin_port), "--log-dir", str(from_flag)],
        {"MCP_TEST_LOG_DIR": str(from_env)},
    )
    assert list(from_flag.glob("mcp-test-server.*.log"))
    assert not list(from_env.glob("mcp-test-server.*.log"))


def test_startup_sweep_removes_stale_logs_but_spares_others(spawn, tmp_path) -> None:
    import os

    log_dir = tmp_path / "sweep"
    log_dir.mkdir()
    old = time.time() - 10 * 86400
    stale = log_dir / "mcp-test-server.9999.2020-01-01.log"
    unrelated = log_dir / "중요한파일.txt"
    stale.write_text("x", encoding="utf-8")
    unrelated.write_text("x", encoding="utf-8")
    os.utime(stale, (old, old))
    os.utime(unrelated, (old, old))

    port, admin_port = free_port(), free_port()
    spawn(["--port", str(port), "--admin-port", str(admin_port), "--log-dir", str(log_dir)])

    assert not stale.exists(), "오래된 로그가 남았다"
    # log_dir 은 사용자가 정한다. 홈 디렉토리를 가리켜도 안전해야 한다.
    assert unrelated.exists(), "패턴에 맞지 않는 파일을 지웠다"
