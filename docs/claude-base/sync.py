#!/usr/bin/env python3
"""manifest.json에 정의된 Claude Code 공식 문서를 재수집한다.

각 문서는 https://code.claude.com/docs/en/<slug>.md 에서 원문 마크다운으로 받아
상단의 "Documentation Index" 안내 블록만 제거하고, manifest의 메타데이터로
YAML 프론트매터를 덧붙여 저장한다. 본문은 손대지 않으므로 재실행 결과는
그대로 diff가 된다.

    python3 docs/claude-base/sync.py            # 전체 갱신
    python3 docs/claude-base/sync.py mcp        # 특정 slug만 갱신
"""

import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

# 원문 최상단에 붙는 안내 배너. 로컬 사본에는 불필요하므로 제거한다.
INDEX_BANNER = re.compile(r"\A(?:>[^\n]*\n)+\s*", re.MULTILINE)


def yaml_quote(text: str) -> str:
    flat = " ".join(text.split())  # 줄바꿈이 들어가면 YAML이 깨지므로 한 줄로 만든다
    return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "claude-base-sync"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def main() -> int:
    only = set(sys.argv[1:])
    today = date.today().isoformat()
    base = MANIFEST["base_url"]

    for doc in MANIFEST["docs"]:
        if only and doc["slug"] not in only:
            continue
        url = f"{base}/{doc['slug']}.md"
        body = INDEX_BANNER.sub("", fetch(url), count=1)

        front = "\n".join(
            [
                "---",
                f"source: {url}",
                f"source_html: {base}/{doc['slug']}",
                f"title: {yaml_quote(doc['title'])}",
                f"category: {doc['category']}",
                f"fetched: {today}",
                f"summary: {yaml_quote(doc['summary'])}",
                "---",
                "",
                "",
            ]
        )

        out = ROOT / doc["path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(front + body, encoding="utf-8")
        print(f"{doc['path']:<32} {len(body):>7,} bytes  <- {url}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
