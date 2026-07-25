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
    # 셸을 거치는 필드는 ${user_config.*} 치환을 거부한다.
    # 산문 언급(주석에서 문법을 설명하는 것)이 아니라, 실행되는 코드에
    # 실제 치환 참조가 있는지를 본다. 주석까지 걸러내면 이 파일의 경고
    # 주석("${user_config.*}를 여기에 쓰면 안 된다")과 충돌하지 않는다.
    helper = (PLUGIN_ROOT / "scripts/connection-id.sh").read_text(encoding="utf-8")
    code_lines = [line for line in helper.splitlines() if not line.strip().startswith("#")]
    assert "${user_config." not in "\n".join(code_lines)


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


def test_check_server_script_names_the_start_command_when_the_server_is_down():
    # 서버가 아예 안 떠 있는 경우가 가장 흔한 실패다. 그 경우 사용자가 실제로
    # 할 수 있는 조치(/mcp-test:server-start)를 안내해야 한다. exit code만
    # 보면 curl이 "000"을 두 번 이어붙여 이 분기를 영영 못 타는 회귀를
    # 잡지 못한다.
    env = {**os.environ, "CLAUDE_PLUGIN_OPTION_SERVER_URL": "http://127.0.0.1:1"}
    result = subprocess.run(
        [str(PLUGIN_ROOT / "hooks/check-server.sh")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "/mcp-test:server-start" in result.stdout


def test_commands_exist():
    for name in ("server-start.md", "server-status.md"):
        assert (PLUGIN_ROOT / "commands" / name).is_file()


def test_plugin_declares_a_non_sensitive_log_dir_option() -> None:
    config = read_json(".claude-plugin/plugin.json")["userConfig"]["log_dir"]
    assert config["type"] == "string"
    # 민감으로 표시하면 Keychain 으로 가서 settings.json 에 남지 않고,
    # 서버가 읽을 수 없게 된다.
    assert config.get("sensitive") is not True
    assert "default" not in config
