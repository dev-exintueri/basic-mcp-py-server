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
