#!/usr/bin/env python3
"""manifest.json에 정의된 Claude Code 공식 문서를 재수집한다.

각 문서는 https://code.claude.com/docs/en/<slug>.md 에서 원문 마크다운으로 받아
상단의 "Documentation Index" 안내 블록만 제거하고, manifest의 메타데이터로
YAML 프론트매터를 덧붙여 저장한다. 본문은 손대지 않으므로 재실행 결과는
그대로 diff가 된다.

본문이 upstream과 동일하면 파일을 다시 쓰지 않는다. 따라서 실행 후
`git status`에 뜨는 파일은 실제로 공식 문서가 바뀐 것뿐이다.
문서 하나가 404이거나 네트워크가 끊겨도 나머지는 계속 처리하고,
마지막에 실패 목록을 요약한다.

    python3 docs/claude-base/sync.py            # 전체 갱신
    python3 docs/claude-base/sync.py mcp        # 특정 slug만 갱신

실패한 문서가 하나라도 있으면 종료 코드 1을 반환한다.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
STATE_FILE = ROOT / "last-sync.txt"

# 원문 최상단에 붙는 안내 배너. 로컬 사본에는 불필요하므로 제거한다.
INDEX_BANNER = re.compile(r"\A(?:>[^\n]*\n)+\s*", re.MULTILINE)

# 기존 로컬 사본의 프론트매터. 본문에도 --- 가 나올 수 있으므로 첫 구분자까지만 본다.
LOCAL_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n+", re.DOTALL)


def yaml_quote(text: str) -> str:
    flat = " ".join(text.split())  # 줄바꿈이 들어가면 YAML이 깨지므로 한 줄로 만든다
    return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "claude-base-sync"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def split_local(text: str) -> tuple[dict, str]:
    """기존 사본을 (프론트매터 dict, 본문)으로 나눈다."""
    m = LOCAL_FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).split("\n"):
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[m.end() :]


def build_frontmatter(doc: dict, url: str, base: str, fetched: str) -> str:
    return (
        "\n".join(
            [
                "---",
                f"source: {url}",
                f"source_html: {base}/{doc['slug']}",
                f"title: {yaml_quote(doc['title'])}",
                f"category: {doc['category']}",
                f"fetched: {fetched}",
                f"summary: {yaml_quote(doc['summary'])}",
                "---",
            ]
        )
        + "\n\n"
    )


def main() -> int:
    only = set(sys.argv[1:])
    today = date.today().isoformat()
    base = MANIFEST["base_url"]

    targets = [d for d in MANIFEST["docs"] if not only or d["slug"] in only]
    if only:
        unknown = only - {d["slug"] for d in MANIFEST["docs"]}
        for slug in sorted(unknown):
            print(f"[skip ] {slug} — manifest.json에 없는 slug")

    tally = {"new": [], "updated": [], "meta": [], "unchanged": [], "failed": []}

    for doc in targets:
        url = f"{base}/{doc['slug']}.md"
        out = ROOT / doc["path"]

        try:
            body = INDEX_BANNER.sub("", fetch(url), count=1)
        except (urllib.error.URLError, OSError) as exc:
            # 페이지 이름이 바뀌거나 네트워크가 끊겨도 나머지 문서는 계속 처리한다.
            reason = getattr(exc, "code", None) or getattr(exc, "reason", exc)
            tally["failed"].append((doc["path"], reason))
            print(f"[fail ] {doc['path']:<30} {reason}  ({url})")
            continue

        old_meta, old_body = ({}, None)
        if out.exists():
            old_meta, old_body = split_local(out.read_text(encoding="utf-8"))

        if old_body is None:
            status = "new"
        elif old_body != body:
            status = "updated"
        else:
            status = "unchanged"

        # 본문이 그대로면 fetched를 건드리지 않는다. 그래야 실제 변경만 diff에 남는다.
        fetched = old_meta.get("fetched", today) if status == "unchanged" else today
        front = build_frontmatter(doc, url, base, fetched)

        if status == "unchanged":
            # 본문은 같아도 manifest의 title/category/summary가 바뀌었을 수 있다.
            if out.read_text(encoding="utf-8") == front + body:
                tally["unchanged"].append(doc["path"])
                continue
            status = "meta"

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(front + body, encoding="utf-8")
        tally[status].append(doc["path"])
        label = {"new": "new  ", "updated": "update", "meta": "meta  "}[status]
        print(f"[{label}] {doc['path']:<30} {len(body):>8,} bytes")

    print()
    summary = "  ".join(
        f"{name}={len(items)}"
        for name, items in tally.items()
        if items or name in ("updated", "unchanged", "failed")
    )
    print(f"{today}  {summary}")

    if tally["failed"]:
        print("\n실패한 문서 — 원문 URL이 바뀌었는지 확인하고 manifest.json의 slug를 고칠 것:")
        for path, reason in tally["failed"]:
            print(f"  {path}  ({reason})")

    if not only:
        STATE_FILE.write_text(
            f"last run: {today}\n{summary}\n"
            + "".join(f"failed: {p} ({r})\n" for p, r in tally["failed"]),
            encoding="utf-8",
        )

    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
