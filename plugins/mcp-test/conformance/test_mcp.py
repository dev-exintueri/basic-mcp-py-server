"""슬라이스 1 — MCP 핵심의 계약."""

from __future__ import annotations

import httpx

from conftest import HEADERS


def test_unauthenticated_post_is_rejected_with_401(server) -> None:
    response = httpx.post(server.mcp_url, timeout=5)
    assert response.status_code == 401
    # 문구는 계약하지 않는다. 키의 존재만 본다.
    assert "error" in response.json()


def test_blank_bearer_token_is_rejected(server) -> None:
    # 원래 브리프는 "Bearer   " (trailing space) 를 보냈지만, httpx 가 쓰는
    # h11 은 앞뒤 공백이 있는 헤더 값을 클라이언트 단에서 막는다
    # (h11._headers.normalize_and_validate -> "Illegal header value") ―
    # 그 값은 와이어에 아예 오르지 못하므로 서버 코드를 전혀 검증하지
    # 못하는 공허한 단언이 된다. "Bearer" (공백 없는 스킴만) 은 같은
    # 인증 실패 분기 (read_identity 가 None 을 반환 -> 401) 를 타므로
    # 대신 이것으로 "빈 토큰" 의도를 검증한다.
    response = httpx.post(
        server.mcp_url, headers={"Authorization": "Bearer"}, timeout=5
    )
    assert response.status_code == 401
