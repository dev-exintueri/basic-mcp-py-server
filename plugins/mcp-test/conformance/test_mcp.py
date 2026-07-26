"""슬라이스 1 — MCP 핵심의 계약."""

from __future__ import annotations

import asyncio
import json

import httpx

from conftest import HEADERS, _call_tool


def test_unauthenticated_post_is_rejected_with_401(server) -> None:
    response = httpx.post(server.mcp_url, timeout=5)
    assert response.status_code == 401
    # 문구는 계약하지 않는다. 키의 존재만 본다.
    assert "error" in response.json()


def test_blank_bearer_token_is_rejected(server) -> None:
    # 원래 브리프는 "Bearer   " (ASCII 스페이스 3개) 를 보냈지만, httpx 가
    # 쓰는 h11 은 앞뒤에 ASCII 공백이 있는 헤더 값을 클라이언트 단에서
    # 막는다 (h11._headers.normalize_and_validate -> "Illegal header
    # value") ― 그 값은 와이어에 아예 오르지 못한다.
    #
    # U+00A0 (NBSP) 는 h11 검증을 통과하면서도 파이썬 str.strip() 과 JS
    # String.prototype.trim() 양쪽 모두 공백(Unicode Zs 범주)으로 취급해
    # 벗겨내므로, read_identity() 의 "prefix 는 맞는데 strip 후 빈
    # 문자열" 분기를 두 런타임에서 동일하게 겨냥할 수 있다 (노드 쪽은
    # Task 4 에서 실제로 확인한다).
    #
    # 다만 str 로 "Bearer \xa0" 를 넘기면 httpx 가 기본 ascii 인코딩을
    # 시도하다 UnicodeEncodeError 를 내고, encoding 을 utf-8 로 바꿔도
    # 와이어에는 0xC2 0xA0 두 바이트가 실려 서버(ASGI, latin-1 디코드)가
    # "Â"(0xC2) + NBSP 두 글자로 읽는다 — strip 이 NBSP 만 벗기고 "Â" 가
    # 남아 subject 가 비지 않으므로 인증이 성공해 버린다. 그래서 이미
    # latin-1 로 인코딩한 bytes 를 직접 넘겨 와이어 바이트와 서버가
    # 디코드할 바이트가 정확히 1:1 이 되게 한다.
    response = httpx.post(
        server.mcp_url,
        headers={"Authorization": b"Bearer \xa0"},
        timeout=5,
    )
    assert response.status_code == 401


def test_unauthenticated_malformed_json_body_is_rejected_with_401(server) -> None:
    """토큰 없이 깨진 JSON 을 보내도 본문 파싱보다 인증이 먼저 돈다.

    최종 리뷰 Important 1(노드 server-node/src/app.ts 의 buildMcpApp())이
    실측한 갈림이다: express.json() 이 authMiddleware() 보다 먼저 등록돼
    있으면 이 요청이 400(JSON 파싱 실패)으로 끝나 버린다. 파이썬은
    AuthMiddleware 가 MCP 앱 바깥이라 본문을 보기도 전에 401을 낸다 — 이
    단언이 지키는 프로덕션 줄은 그 등록 순서 자체다.
    """
    response = httpx.post(
        server.mcp_url,
        headers={"Content-Type": "application/json"},
        content=b"{not valid json",
        timeout=5,
    )
    assert response.status_code == 401
    assert "error" in response.json()


def test_unauthenticated_oversized_body_is_rejected_with_401(server) -> None:
    """토큰 없이 100KB 를 넘는 본문을 보내도 크기 검사보다 인증이 먼저 돈다.

    express.json() 의 기본 limit(100kb)이 authMiddleware() 보다 먼저 돌면
    이 요청은 413(Payload Too Large)으로 끝난다. 본문은 200KB — 기본
    limit 을 확실히 넘기되 이 서버가 실제로 검증한 무제한 상한(측정:
    100MB 까지 echo 왕복 성공, app.ts 의 buildMcpApp() 주석 참고)에는 한참
    못 미치는 크기다.
    """
    response = httpx.post(
        server.mcp_url,
        headers={"Content-Type": "application/json"},
        content=b"x" * 200_000,
        timeout=5,
    )
    assert response.status_code == 401
    assert "error" in response.json()


# 서버 소스의 절대 경로나 의존성의 파일·행 번호가 새어 나가는지 보는 단서.
# 최종 리뷰 Important 2 가 실측한 경로다 — 노드가 오류 처리기 없이 깨진
# JSON 을 받으면 body-parser 의 스택 트레이스가 담긴 HTML 을 그대로
# 돌려줬다(파일 경로와 행 번호 포함).
_PATH_LEAK_MARKERS = ("/Users/", "node_modules", "site-packages", ".ts:", ".js:", ".py:")


def test_error_responses_are_json_with_an_error_key_and_no_server_paths(server) -> None:
    """오류 응답은 JSON {error} 이고 서버 소스의 경로를 흘리지 않는다.

    토큰이 있어도 본문이 깨져 있으면 오류가 난다 — 그 오류가 app.ts 의
    errorHandler(노드) / AuthMiddleware 뒤의 MCP 앱(파이썬) 양쪽 모두를
    거쳐 나가는 응답을 본다. 노드는 오류 처리기가 없으면 finalhandler 가
    body-parser 의 스택을 그대로 HTML `<pre>` 에 박아 냈다(실측, 최종
    리뷰 Important 2) — errorHandler.ts 의 res.status(status).json({error})
    가 지키는 계약이 이 단언이다.
    """
    response = httpx.post(
        server.mcp_url,
        headers={
            "Authorization": "Bearer alice",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        content=b"{not valid json",
        timeout=5,
    )
    assert response.status_code >= 400
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert "error" in payload
    body_text = response.text
    for marker in _PATH_LEAK_MARKERS:
        assert marker not in body_text, f"{marker!r} 가 오류 응답에 그대로 새어 나갔다: {body_text}"


def test_echo_round_trips_a_body_larger_than_100kb(server) -> None:
    """echo 는 길이 제한 없는 인자다 — 100KB 를 넘는 문자열도 그대로 돌아온다.

    express.json() 의 기본 limit(100kb)을 그대로 두면 이 호출이 노드에서만
    413 으로 실패한다(최종 리뷰 Important 1). 150KB 는 그 기본 limit 을
    확실히 넘기는 크기다.
    """
    text = "가" * 150_000
    result = asyncio.run(_call_tool(server.mcp_url, HEADERS, "echo", {"text": text}))
    assert result.content[0].text == text


from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TOOL_NAMES = ["echo", "ping", "sessions", "whoami"]


async def _tools(url: str, headers: dict[str, str]):
    async with streamablehttp_client(url, headers=headers) as (read, write, get_sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            return get_sid(), listing.tools


def test_stateful_session_id_is_issued(server) -> None:
    session_id, _ = asyncio.run(_tools(server.mcp_url, HEADERS))
    # stateless 로 두면 이 값이 없다. session_view 의 mcp_session_id 가
    # 영원히 null 이 되므로 계약이 깨진다.
    assert session_id


def test_exactly_four_tools_are_exposed(server) -> None:
    _, tools = asyncio.run(_tools(server.mcp_url, HEADERS))
    assert sorted(t.name for t in tools) == TOOL_NAMES


def test_echo_returns_the_input_verbatim(server) -> None:
    result = asyncio.run(_call_tool(server.mcp_url, HEADERS, "echo", {"text": "안녕 🌍"}))
    assert result.content[0].text == "안녕 🌍"


def test_ping_reports_process_shape(server) -> None:
    result = asyncio.run(_call_tool(server.mcp_url, HEADERS, "ping", {}))
    payload = json.loads(result.content[0].text)
    # 값이 아니라 형태만 본다. pid 는 두 런타임에서 다르다.
    assert isinstance(payload["pid"], int)
    assert isinstance(payload["uptime_seconds"], (int, float))
    assert isinstance(payload["session_count"], int)
    assert isinstance(payload["server_time"], str)


def test_whoami_reads_the_connection_id_from_the_header(server) -> None:
    result = asyncio.run(_call_tool(server.mcp_url, HEADERS, "whoami", {}))
    payload = json.loads(result.content[0].text)
    # SDK 의 콜백 인자 규약을 틀리면 여기서 잡힌다. 인자 없는 도구의 콜백은
    # (extra) 하나만 받는다 — (_args, extra) 로 쓰면 헤더를 못 읽는다.
    assert payload["instance_id"] == HEADERS["X-Client-Instance"]
    assert payload["known"] is True


def test_session_view_has_the_contracted_keys(server) -> None:
    result = asyncio.run(_call_tool(server.mcp_url, HEADERS, "sessions", {}))
    payload = json.loads(result.content[0].text)
    assert payload["count"] >= 1
    assert set(payload["sessions"][0]) == {
        "instance_id", "subject", "project", "label", "mcp_session_id",
        "connected_at", "last_seen", "call_count", "blocked", "stale",
    }
