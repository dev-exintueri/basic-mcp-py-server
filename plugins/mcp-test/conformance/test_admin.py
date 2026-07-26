"""슬라이스 2 — 관리 API 의 계약."""

from __future__ import annotations

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from conftest import HEADERS, _call_tool

STATUS_KEYS = {
    "pid", "runtime", "uptime_seconds", "mcp_endpoint",
    "session_count", "sessions", "log_dir", "log_file",
}


def test_status_has_the_contracted_keys(server) -> None:
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert set(payload) == STATUS_KEYS
    assert payload["runtime"] == server.runtime
    assert isinstance(payload["pid"], int)


def test_status_lists_connected_sessions(server) -> None:
    # 세션 하나를 만들어 레지스트리에 레코드를 남긴다. ping 결과는 쓰지 않는다.
    asyncio.run(_call_tool(server.mcp_url, HEADERS, "ping", {}))
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert payload["session_count"] == 1
    assert payload["sessions"][0]["instance_id"] == HEADERS["X-Client-Instance"]


def test_disconnecting_removes_the_session_record(server) -> None:
    # 일부러 conftest 의 _call_tool 을 안 쓴다. 그 헬퍼는 terminate_on_close=False 로
    # DELETE 를 억눌러서 슬라이스 2 의 다른 테스트들이 세션을 계속 볼 수 있게 하는
    # 것이 목적이다 (연결 종료 후에도 레지스트리 레코드가 남아 있어야 하는
    # 테스트들). 여기서는 정반대로 "연결이 끊기면 레코드가 지워진다"는 것 자체가
    # 단언 대상이라, SDK 기본 동작(streamablehttp_client 의 terminate_on_close=True)이
    # 실제로 DELETE 를 보내게 둬야 한다. _call_tool 로 바꾸면 이 테스트가 통과는
    # 하지만 DELETE 분기를 더 이상 겨냥하지 않게 된다.
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                await session.call_tool("ping", {})
                mid = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
                assert mid["session_count"] == 1
        # 블록을 나가면 SDK 기본 동작(terminate_on_close=True)으로 DELETE 가 발사된다.

    asyncio.run(run())
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert payload["session_count"] == 0


def test_sessions_fragment_escapes_client_supplied_values(server) -> None:
    headers = {**HEADERS, "X-Client-Label": "<script>x</script>"}

    async def run():
        # terminate_on_close=False: 기본값(True)이면 이 블록을 빠져나갈 때
        # DELETE 로 세션 종료를 알려 레지스트리 레코드가 지워진다 (conftest
        # 의 _call_tool 과 같은 이유). 이 테스트는 그 레코드가 남아
        # /fragments/sessions 에 렌더링되는 것을 봐야 하므로 꺼 둔다.
        async with streamablehttp_client(
            server.mcp_url, headers=headers, terminate_on_close=False
        ) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()

    asyncio.run(run())
    body = httpx.get(f"{server.admin_url}/fragments/sessions", timeout=5).text
    # 값은 클라이언트가 정한다. 날것으로 넣으면 관리 화면에 스크립트가 실린다.
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body


def test_sessions_fragment_has_the_contracted_columns(server) -> None:
    body = httpx.get(f"{server.admin_url}/fragments/sessions", timeout=5).text
    for column in ("연결 ID", "subject", "project", "label", "연결 시각", "마지막 호출", "호출"):
        assert column in body


def test_block_then_unblock_round_trip(server) -> None:
    asyncio.run(_call_tool(server.mcp_url, HEADERS, "ping", {}))
    instance = HEADERS["X-Client-Instance"]

    blocked = httpx.post(f"{server.admin_url}/api/sessions/{instance}/block", timeout=5)
    assert blocked.status_code == 200
    assert blocked.json() == {"instance_id": instance, "action": "block"}

    # 차단된 연결은 403 을 받는다.
    denied = httpx.post(server.mcp_url, headers=HEADERS, timeout=5)
    assert denied.status_code == 403

    unblocked = httpx.post(f"{server.admin_url}/api/sessions/{instance}/unblock", timeout=5)
    assert unblocked.status_code == 200


def test_block_on_unknown_instance_is_404(server) -> None:
    response = httpx.post(f"{server.admin_url}/api/sessions/nope/block", timeout=5)
    assert response.status_code == 404
    assert "error" in response.json()


# 서버 소스의 절대 경로나 의존성의 파일·행 번호가 새어 나가는지 보는 단서.
# test_mcp.py 의 같은 이름의 상수와 목적이 같다 — 파일을 독립적으로 유지하려고
# 옮기지 않고 그대로 둔다.
_PATH_LEAK_MARKERS = ("/Users/", "node_modules", "site-packages", ".ts:", ".js:", ".py:")


def test_admin_error_responses_are_json_with_an_error_key_and_no_server_paths(server) -> None:
    """관리 앱의 오류 처리기(있다면)에도 커버리지가 있어야 한다.

    관리 앱은 인증이 없는 리스너다 — 여기서 오류 처리기가 새면 토큰 없이도
    닿는다(최종 리뷰 재재검토 Minor 1). 노드의 express.urlencoded() 는
    본문 크기와 무관하게 parameterLimit(기본 1000)을 넘기면 413 을 낸다 —
    admin.ts 의 limit: Infinity(Minor 2) 는 바이트 크기 상한만 없앨 뿐,
    이 카운트 상한과는 무관하다. 파이썬은 이 라우트에서 본문을 전혀 읽지
    않으므로(경로만 보고 404) 두 런타임의 상태 코드가 같을 이유는 없다 —
    여기서 보는 것은 "오류가 나면 그 응답이 JSON {error} 이고 서버 파일
    경로를 흘리지 않는다"는 성질 하나뿐이다.
    """
    body = "&".join(f"k{i}=v" for i in range(1100))
    response = httpx.post(
        f"{server.admin_url}/api/sessions/nope/block",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        content=body.encode("utf-8"),
        timeout=5,
    )
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert "error" in payload
    body_text = response.text
    for marker in _PATH_LEAK_MARKERS:
        assert marker not in body_text, f"{marker!r} 가 오류 응답에 그대로 새어 나갔다: {body_text}"


def test_html_form_post_redirects_to_index(server) -> None:
    asyncio.run(_call_tool(server.mcp_url, HEADERS, "ping", {}))
    instance = HEADERS["X-Client-Instance"]
    response = httpx.post(
        f"{server.admin_url}/api/sessions/{instance}/block",
        headers={"Accept": "text/html"},
        follow_redirects=False,
        timeout=5,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_index_page_renders(server) -> None:
    response = httpx.get(f"{server.admin_url}/", timeout=5)
    assert response.status_code == 200
    assert "MCP 테스트 서버" in response.text
