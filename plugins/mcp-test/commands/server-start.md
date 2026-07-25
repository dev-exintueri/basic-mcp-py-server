---
description: MCP 테스트 서버를 기동한다
---

MCP 테스트 서버를 기동한다.

1. 이미 떠 있는지 확인한다. `curl -s -o /dev/null -w '%{http_code}' --max-time 2 -X POST http://127.0.0.1:8765/mcp` 가 `401`을 반환하면 이미 기동된 것이다. 그 사실을 알리고 여기서 멈춘다.
2. 떠 있지 않으면 백그라운드로 기동한다.

   ```bash
   uv run --directory ${CLAUDE_PLUGIN_ROOT}/server mcp-test-server
   ```

3. 기동되면 MCP 엔드포인트(`http://127.0.0.1:8765/mcp`)와 관리 페이지(`http://127.0.0.1:8766/`) 주소를 알린다.
4. 새 세션에서 서버에 붙으려면 `/mcp`로 연결 상태를 확인하라고 안내한다.

포트를 바꾸려면 `--port`와 `--admin-port`를 쓴다. 이 경우 플러그인 설정의 `server_url`도 함께 바꿔야 한다.
