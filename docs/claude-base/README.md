# docs/claude-base 인벤토리

운영 규칙은 [CLAUDE.md](./CLAUDE.md)에, 수집 대상 정의와 한국어 요약은 [manifest.json](./manifest.json)에 있다.
이 파일은 무엇이 들어 있고 어디부터 읽어야 하는지에 대한 안내다.

최초 수집: 2026-07-25 / 문서 20개 / 원문: https://code.claude.com/docs/en/

## 카테고리

| category | 뜻 |
|---|---|
| `mcp-core` | MCP 연결 자체 |
| `mcp-build` | MCP 서버를 **만드는** 쪽 |
| `mcp-ops` | 설정·권한·배포·디버깅 |
| `concept` | 개념·용어 |

## 수집된 문서

| 파일 | category | 원문 |
|---|---|---|
| `mcp.md` | mcp-core | https://code.claude.com/docs/en/mcp |
| `mcp-quickstart.md` | mcp-core | https://code.claude.com/docs/en/mcp-quickstart |
| `agent-sdk/mcp.md` | mcp-build | https://code.claude.com/docs/en/agent-sdk/mcp |
| `agent-sdk/custom-tools.md` | mcp-build | https://code.claude.com/docs/en/agent-sdk/custom-tools |
| `agent-sdk/python.md` | mcp-build | https://code.claude.com/docs/en/agent-sdk/python |
| `agent-sdk/tool-search.md` | mcp-build | https://code.claude.com/docs/en/agent-sdk/tool-search |
| `channels.md` | mcp-build | https://code.claude.com/docs/en/channels |
| `channels-reference.md` | mcp-build | https://code.claude.com/docs/en/channels-reference |
| `managed-mcp.md` | mcp-ops | https://code.claude.com/docs/en/managed-mcp |
| `settings.md` | mcp-ops | https://code.claude.com/docs/en/settings |
| `env-vars.md` | mcp-ops | https://code.claude.com/docs/en/env-vars |
| `permissions.md` | mcp-ops | https://code.claude.com/docs/en/permissions |
| `cli-reference.md` | mcp-ops | https://code.claude.com/docs/en/cli-reference |
| `hooks.md` | mcp-ops | https://code.claude.com/docs/en/hooks |
| `plugins-reference.md` | mcp-ops | https://code.claude.com/docs/en/plugins-reference |
| `tools-reference.md` | mcp-ops | https://code.claude.com/docs/en/tools-reference |
| `debug-your-config.md` | mcp-ops | https://code.claude.com/docs/en/debug-your-config |
| `features-overview.md` | concept | https://code.claude.com/docs/en/features-overview |
| `glossary.md` | concept | https://code.claude.com/docs/en/glossary |
| `agent-sdk/overview.md` | concept | https://code.claude.com/docs/en/agent-sdk/overview |

각 문서의 한국어 요약은 파일 상단 프론트매터의 `summary` 또는 `manifest.json`에 있다.

## 어디부터 읽나

- **MCP 서버를 구현하는 중이라면** `agent-sdk/mcp.md`(클라이언트가 서버에 기대하는 계약) → `agent-sdk/custom-tools.md`(도구 스키마·구조화된 출력·이미지 반환) → `agent-sdk/python.md`(Python 타입).
- **연결이 안 될 때는** `debug-your-config.md` → `mcp-quickstart.md`의 Troubleshooting → `mcp.md`의 스코프/인증 절.
- **도구 이름을 정할 때는** `permissions.md`를 먼저. 사용자가 `mcp__<server>__<tool>` 패턴으로 허용·차단하므로 이름 설계가 곧 권한 설계다.
- **팀에 배포할 때는** `plugins-reference.md`(플러그인에 `.mcp.json` 번들) + `managed-mcp.md`(조직 allowlist).

## 선별 근거

172개 영어 문서를 전부 내려받아 본문의 `MCP` 언급 횟수로 순위를 매긴 결과 상위권은 아래와 같았다.

```
 413  changelog.md          (주간 변경 이력 — 제외)
 365  mcp.md
 188  agent-sdk/mcp.md
 155  managed-mcp.md
 146  mcp-quickstart.md
 138  agent-sdk/typescript.md  (TS 레퍼런스 — 이 저장소는 Python이라 제외)
 128  agent-sdk/python.md
 104  hooks.md
  91  monitoring-usage.md   (사용량 대시보드 중심 — 제외)
  81  env-vars.md
  79  settings.md
  73  plugins-reference.md
  58  channels-reference.md
  54  agent-sdk/custom-tools.md
```

여기서 (a) MCP 전용 문서, (b) MCP 서버를 만드는 쪽 문서, (c) MCP 설정·권한·디버깅이 실제로 기술된 레퍼런스를 골랐다.

## 새 문서가 생겼는지 다시 확인하려면

최초 수집과 같은 방법으로 순위를 다시 매긴다.

```bash
# 현재 영어 문서 전체 목록
curl -sL https://code.claude.com/docs/llms.txt \
  | grep -o 'https://code.claude.com/docs/en/[^)]*\.md' | sort -u > /tmp/en_urls.txt

# 전부 받아서 MCP 언급 횟수로 정렬 (파일명의 __ 는 원문 경로의 / 를 치환한 것)
mkdir -p /tmp/ccdocs && cd /tmp/ccdocs
xargs -P 12 -I{} sh -c 'u="{}"; f=$(echo "$u" | sed "s|.*/docs/en/||; s|/|__|g"); curl -sfL "$u" -o "$f"' < /tmp/en_urls.txt
for f in *.md; do printf "%5s  %s\n" "$(grep -oi mcp "$f" | wc -l)" "$f"; done | sort -rn | head -40
```

`manifest.json`에 없는 문서가 상위권에 올라왔다면 추가를 검토한다.
