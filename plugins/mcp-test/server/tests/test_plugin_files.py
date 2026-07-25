"""플러그인 파일이 규격에 맞는지 검사한다.

서버 코드가 아니라 배포 산출물을 검증하는 테스트다. 오타 하나가 설치 후에야
드러나는 것을 막는다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def read_json(relative: str):
    return json.loads((PLUGIN_ROOT / relative).read_text(encoding="utf-8"))


def test_plugin_manifest_declares_both_user_config_options():
    manifest = read_json(".claude-plugin/plugin.json")
    assert manifest["name"] == "mcp-test"
    options = manifest["userConfig"]
    assert options["server_url"]["default"] == "http://127.0.0.1:8765"
    assert options["auth_token"]["sensitive"] is True
    assert options["auth_token"]["required"] is True


def test_mcp_config_uses_http_with_all_three_substitutions():
    server = read_json(".mcp.json")["mcpServers"]["test-server"]
    # url이 있는데 type이 없으면 Claude Code가 설정 오류로 건너뛴다
    assert server["type"] == "http"
    assert server["url"] == "${user_config.server_url}/mcp"
    headers = server["headers"]
    assert headers["Authorization"] == "Bearer ${user_config.auth_token}"
    assert headers["X-Client-Project"] == "${CLAUDE_PROJECT_DIR}"
    assert headers["X-Client-Label"] == "${MCP_TEST_LABEL:-unnamed}"
    assert server["headersHelper"] == "${CLAUDE_PLUGIN_ROOT}/scripts/connection-id.sh"


def test_headers_helper_does_not_reference_user_config():
    # 셸을 거치는 필드는 ${user_config.*}를 거부한다
    helper = (PLUGIN_ROOT / "scripts/connection-id.sh").read_text(encoding="utf-8")
    assert "user_config" not in helper


def test_shell_scripts_are_executable():
    for relative in ("scripts/connection-id.sh", "hooks/check-server.sh"):
        assert os.access(PLUGIN_ROOT / relative, os.X_OK), relative


def test_connection_id_script_emits_distinct_json_ids():
    script = str(PLUGIN_ROOT / "scripts/connection-id.sh")
    first = json.loads(subprocess.run([script], capture_output=True, text=True, check=True).stdout)
    second = json.loads(subprocess.run([script], capture_output=True, text=True, check=True).stdout)
    assert set(first) == {"X-Client-Instance"}
    assert first["X-Client-Instance"]
    assert first["X-Client-Instance"] != second["X-Client-Instance"]


def test_session_start_hook_points_at_the_check_script():
    hooks = read_json("hooks/hooks.json")["hooks"]["SessionStart"]
    commands = [h["command"] for entry in hooks for h in entry["hooks"]]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/check-server.sh" in commands


def test_check_server_script_reads_the_plugin_option_env_var():
    script = (PLUGIN_ROOT / "hooks/check-server.sh").read_text(encoding="utf-8")
    assert "CLAUDE_PLUGIN_OPTION_SERVER_URL" in script


def test_check_server_script_never_blocks_the_session():
    env = {**os.environ, "CLAUDE_PLUGIN_OPTION_SERVER_URL": "http://127.0.0.1:1"}
    result = subprocess.run(
        [str(PLUGIN_ROOT / "hooks/check-server.sh")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0


def test_commands_exist():
    for name in ("server-start.md", "server-status.md"):
        assert (PLUGIN_ROOT / "commands" / name).is_file()
