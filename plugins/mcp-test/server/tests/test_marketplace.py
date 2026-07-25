import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_marketplace_lists_the_plugin_with_a_relative_source():
    catalog = json.loads(
        (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    assert catalog["name"] == "basic-mcp-py-server"
    assert catalog["owner"]["name"]

    entries = {p["name"]: p for p in catalog["plugins"]}
    assert "mcp-test" in entries
    source = entries["mcp-test"]["source"]
    # 상대 경로는 ./ 로 시작해야 하고 마켓플레이스 루트 기준으로 해석된다
    assert source == "./plugins/mcp-test"
    assert (REPO_ROOT / source).is_dir()


def test_marketplace_name_is_not_reserved():
    reserved = {
        "claude-code-marketplace",
        "claude-code-plugins",
        "claude-plugins-official",
        "claude-plugins-community",
        "claude-community",
        "anthropic-marketplace",
        "anthropic-plugins",
        "agent-skills",
        "anthropic-agent-skills",
        "knowledge-work-plugins",
        "life-sciences",
        "claude-for-legal",
        "claude-for-financial-services",
        "financial-services-plugins",
        "first-party-plugins",
        "healthcare",
    }
    catalog = json.loads(
        (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    assert catalog["name"] not in reserved


def test_readme_documents_the_install_commands():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "claude plugin marketplace add dev-exintueri/basic-mcp-py-server" in readme
    assert "claude plugin install mcp-test@basic-mcp-py-server" in readme
