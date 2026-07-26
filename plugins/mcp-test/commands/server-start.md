---
description: MCP 테스트 서버를 기동한다 (python 또는 node)
---

MCP 테스트 서버를 기동한다. **런타임을 반드시 명시한다.**

인자로 `python` 또는 `node` 를 받는다: `$ARGUMENTS`

1. 인자가 비어 있으면 `python` 과 `node` 중 무엇을 띄울지 사용자에게 묻고 멈춘다. 기본값을 임의로 고르지 않는다.
2. 인자가 두 값 중 어느 것도 아니면 두 런타임 이름을 알리고 멈춘다.
3. 이미 떠 있는지 확인한다. `curl -s --max-time 2 http://127.0.0.1:8766/api/status` 가 응답하면 이미 기동된 것이다. 응답의 `runtime` 과 `pid` 를 읽어 **어느 런타임이 떠 있는지** 알린다. 다른 런타임으로 바꾸려면 먼저 내려야 한다고 안내하고 멈춘다.
4. 떠 있지 않으면 백그라운드로 기동한다.

   `python` 인 경우:
   ```bash
   uv run --directory ${CLAUDE_PLUGIN_ROOT}/server mcp-test-server
   ```

   `node` 인 경우:
   ```bash
   cd ${CLAUDE_PLUGIN_ROOT}/server-node && npm install && npm run build && node dist/main.js
   ```

5. 기동되면 MCP 엔드포인트(`http://127.0.0.1:8765/mcp`)와 관리 페이지(`http://127.0.0.1:8766/`) 주소를 런타임과 함께 알린다.
6. 새 세션에서 서버에 붙으려면 `/mcp`로 연결 상태를 확인하라고 안내한다.

두 런타임은 같은 포트를 쓰므로 **동시에 띄울 수 없다.** MCP 클라이언트 쪽 설정(`.mcp.json`)은 어느 쪽이 떠 있든 그대로 동작한다.

포트를 바꾸려면 `--port`와 `--admin-port`를 쓴다. 이 경우 플러그인 설정의 `server_url`도 함께 바꿔야 한다.
