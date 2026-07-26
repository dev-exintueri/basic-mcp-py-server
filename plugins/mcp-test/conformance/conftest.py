"""두 런타임을 같은 단언으로 검증하기 위한 기동 하네스.

--target 으로 무엇을 띄울지 고른다. 단언은 테스트 파일에 있고, 이 파일은
"어떻게 띄우는가" 만 안다. 그 차이가 두 런타임 사이의 유일한 차이여야 한다.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "mcp-test"
PY_SERVER = PLUGIN_ROOT / "server"
NODE_SERVER = PLUGIN_ROOT / "server-node"

HEADERS = {
    "Authorization": "Bearer alice",
    "X-Client-Instance": "abc123def456",
    "X-Client-Project": "/tmp/proj",
    "X-Client-Label": "left",
}


async def _call_tool(url: str, headers: dict[str, str], tool_name: str, tool_args: dict):
    """세션 하나를 열어 도구 하나를 부르고 결과를 돌려준다.

    슬라이스 1(test_mcp.py)과 슬라이스 2(test_admin.py)가 함께 쓴다. 세션을
    맺기만 하고 결과를 버려도 되는 호출(레지스트리에 레코드를 남기는 것이
    목적인 경우)도 이 함수로 충분하다 — 반환값을 그냥 안 받으면 된다.

    terminate_on_close=False 를 명시한다. mcp SDK 는 기본값(True)일 때 이
    async with 블록을 빠져나가는 순간 DELETE 로 세션 종료를 서버에 알리고,
    서버의 AuthMiddleware 는 DELETE 를 "레지스트리에서 지워라"로 읽는다
    (auth.py). 그러면 이 함수가 반환하기도 전에 레지스트리 레코드가 이미
    사라져, 호출부가 이어서 /api/status 를 봤을 때 세션이 안 잡힌다.
    """
    async with streamablehttp_client(
        url, headers=headers, terminate_on_close=False
    ) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            return await session.call_tool(tool_name, tool_args)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--target",
        action="store",
        default="python",
        choices=("python", "node"),
        help="검증할 서버 런타임",
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class ServerHandle:
    runtime: str
    port: int
    admin_port: int
    log_dir: Path
    mcp_url: str
    admin_url: str
    proc: subprocess.Popen
    stdout_path: Path

    def output(self) -> str:
        try:
            return self.stdout_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def log_text(self) -> str:
        """서버가 남긴 로그 파일 전체. 없으면 빈 문자열."""
        files = sorted(self.log_dir.glob("mcp-test-server.*.log"))
        return "".join(f.read_text(encoding="utf-8", errors="replace") for f in files)


def base_command(runtime: str) -> list[str]:
    """서버를 띄우는 명령. 인자는 붙이지 않는다.

    두 런타임의 차이는 이 함수 하나에 갇혀 있어야 한다. 인자를 여기서 함께
    조립하면 인자를 바꿔 띄우고 싶은 테스트가 슬라이싱으로 떼어내게 되고,
    그것은 명령이 길어질 때 조용히 깨진다.
    """
    if runtime == "python":
        return ["uv", "run", "--directory", str(PY_SERVER), "mcp-test-server"]
    return ["node", str(NODE_SERVER / "dist" / "main.js")]


def _ensure_built(runtime: str) -> None:
    """노드 타깃은 빌드가 최신이어야 한다.

    dist/ 가 낡았거나 없으면 어제 코드를 검증하고 초록을 보고한다. skip 하지
    않는 것도 중요하다 — skip 은 요약 줄에서 "덮었다" 로 읽힌다.
    """
    if runtime != "node":
        return
    if not (NODE_SERVER / "node_modules").is_dir():
        raise RuntimeError(
            f"{NODE_SERVER}/node_modules 가 없다. npm install 을 먼저 돌려라. "
            "이 상황을 skip 으로 넘기지 않는다"
        )
    result = subprocess.run(
        ["npm", "run", "build"], cwd=NODE_SERVER, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"노드 빌드 실패:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="function")
def server(request: pytest.FixtureRequest, tmp_path: Path):
    runtime = request.config.getoption("--target")
    _ensure_built(runtime)

    port, admin_port = free_port(), free_port()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    stdout_path = tmp_path / "server.out"

    args = [
        *base_command(runtime),
        "--port", str(port),
        "--admin-port", str(admin_port),
        "--log-dir", str(log_dir),
    ]
    with stdout_path.open("wb") as sink:
        proc = subprocess.Popen(args, stdout=sink, stderr=subprocess.STDOUT)

    handle = ServerHandle(
        runtime=runtime,
        port=port,
        admin_port=admin_port,
        log_dir=log_dir,
        mcp_url=f"http://127.0.0.1:{port}/mcp",
        admin_url=f"http://127.0.0.1:{admin_port}",
        proc=proc,
        stdout_path=stdout_path,
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"서버가 기동 중 죽었다:\n{handle.output()}")
        try:
            # 인증 없는 POST 에 401 이 오면 살아 있는 것이다. 401 은 서버가
            # 떴다는 것과 인증이 실제로 걸려 있다는 것을 함께 증명한다.
            if httpx.post(handle.mcp_url, timeout=1).status_code == 401:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"서버가 30초 안에 뜨지 않았다:\n{handle.output()}")

    try:
        yield handle
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
