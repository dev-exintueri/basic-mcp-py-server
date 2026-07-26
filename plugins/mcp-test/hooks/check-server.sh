#!/bin/sh
# 플러그인 설정 값을 환경변수로 받는 예시.
#
# 셸에서 실행되는 필드는 ${user_config.*}를 거부한다. 대신 Claude Code가
# 모든 userConfig 값을 훅 프로세스에 CLAUDE_PLUGIN_OPTION_<KEY>로 내려준다.
#
# 생존 확인은 인증 없이 /mcp에 POST해서 401이 오는지 보는 것이다.
# 401은 서버가 살아 있다는 것과 인증이 실제로 걸려 있다는 것을 함께 증명한다.
set -u

url="${CLAUDE_PLUGIN_OPTION_SERVER_URL:-http://127.0.0.1:8765}"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 -X POST "$url/mcp" 2>/dev/null || true)
code=${code:-000}

case "$code" in
  401)
    ;;
  000)
    echo "MCP 테스트 서버($url)가 응답하지 않는다. /mcp-test:server-start python 또는 /mcp-test:server-start node 로 띄워라."
    ;;
  *)
    echo "MCP 테스트 서버($url)가 예상 밖의 상태다: HTTP $code (401을 기대했다)."
    ;;
esac

# 훅은 어떤 경우에도 세션을 막지 않는다.
exit 0
