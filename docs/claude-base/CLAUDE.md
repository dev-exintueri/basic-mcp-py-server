# docs/claude-base 취급 규칙

이 디렉토리는 Anthropic 공식 문서(https://code.claude.com/docs)의 **MCP 관련 페이지를 그대로 내려받은 미러**다. 직접 쓴 해설이 아니다.

- **여기 있는 `.md` 파일의 본문을 편집하지 않는다.** 원문과의 diff를 유지하는 것이 이 디렉토리의 존재 이유이며, 편집분은 다음 갱신 때 덮어써진다. 내용에 문제가 있으면 고치지 말고 갱신한다.
- 예외는 `CLAUDE.md`, `README.md`, `manifest.json`, `sync.py` 네 파일뿐이다. 이 넷은 직접 관리한다. `last-sync.txt`는 `sync.py`가 매 실행마다 덮어쓰는 실행 기록이므로 손대지 않는다.
- 본문 내부 링크는 `/docs/en/mcp-quickstart` 같은 사이트 절대경로다. 로컬에서 열리지 않으니 `https://code.claude.com`을 앞에 붙여 읽는다. 일부러 고치지 않았다.
- 문서 내용은 **스냅샷**이다. 각 파일의 `fetched`는 그 사본의 내용이 마지막으로 바뀐 날, `last-sync.txt`는 마지막으로 upstream과 대조한 날이다. 실제 동작이 문서와 다르면 문서가 낡았을 가능성을 먼저 의심하고, 갱신한 뒤 다시 확인한다.
- MCP 프로토콜 자체의 규격(JSON-RPC 메시지, 수명주기, 서버 capability 정의)은 여기 없다. 그건 https://modelcontextprotocol.io 소관이고, 이 디렉토리는 **Claude Code가 MCP를 어떻게 다루는가**만 담는다.

무엇이 수집돼 있고 어디부터 읽어야 하는지는 [README.md](./README.md), 대상 목록과 한국어 요약은 [manifest.json](./manifest.json)에 있다.

## 수집 방식

공식 문서는 슬러그 뒤에 `.md`를 붙이면 원문 마크다운을 그대로 준다. **이 디렉토리 운영의 핵심이 이것이다.**

```
https://code.claude.com/docs/en/mcp      → HTML (1.7MB)
https://code.claude.com/docs/en/mcp.md   → 마크다운 원문 (76KB)
```

전체 목록은 `sitemap.xml`(URL 1,976개, 12개 언어)과 `llms.txt`(제목·설명 포함) 양쪽에 있다. 영어판이 정본(172개, 번역본은 각 164개)이므로 **`en`만 대상으로 한다.**

- 파일 경로는 원문 URL 경로를 그대로 미러링한다. `docs/en/agent-sdk/mcp.md` → `agent-sdk/mcp.md`. 파일 위치에서 출처 URL을 복원할 수 있다.
- 저장 시 상단의 "Documentation Index" 안내 배너 3줄만 제거하고, 아래 프론트매터를 덧붙인다. 그 아래는 원문 그대로다.
  ```yaml
  ---
  source: https://code.claude.com/docs/en/mcp.md      # 마크다운 원문
  source_html: https://code.claude.com/docs/en/mcp    # 사람이 볼 URL
  title: "Connect Claude Code to tools via MCP"       # 원문 제목 (영문 유지)
  category: mcp-core                                  # mcp-core|mcp-build|mcp-ops|concept
  fetched: 2026-07-25                                 # 이 사본이 마지막으로 갱신된 날
  summary: "…"                                        # 한국어 요약 (manifest.json에서 관리)
  ---
  ```
  `fetched`는 **이 로컬 사본이 마지막으로 갱신된 날**이다 — 최초 수집일이거나, 이후 upstream 변경을 반영한 날. 원문이 그대로면 갱신되지 않으므로 "마지막으로 실행한 날"과는 다르다. 공식 문서가 실제로 언제 수정됐는지는 여기서 알 수 없다. 마지막 대조일은 `last-sync.txt`에 있다.

## 갱신

### 기존 문서 최신화

```bash
python3 docs/claude-base/sync.py            # 전체
python3 docs/claude-base/sync.py mcp        # 특정 slug만
```

`manifest.json`을 읽어 다시 받고 배너를 떼고 프론트매터를 붙인다. **본문이 upstream과 같으면 파일을 다시 쓰지 않는다.** 그래서 실행 후 `git status`에 뜨는 `.md` 파일은 실제로 공식 문서가 바뀐 것뿐이고, `git diff docs/claude-base/*.md`가 곧 upstream 변경 내역이 된다. 한국어 `summary`는 `manifest.json`에 있으므로 항상 보존된다.

단 `last-sync.txt`는 실행 기록이라 날짜가 바뀌면 항상 갱신된다. 아무것도 안 바뀐 날의 실행도 이 파일 하나는 수정된 것으로 뜬다.

실행 결과는 다음과 같이 요약된다. `last-sync.txt`에도 같은 내용이 남는다(전체 실행일 때만).

```
[update] mcp.md                           76,109 bytes
[fail ] glossary.md                    404  (https://code.claude.com/docs/en/glossary.md)

2026-07-25  updated=1  unchanged=18  failed=1

```

| 표시 | 뜻 |
|---|---|
| `new` | 새로 추가된 문서를 처음 받음 |
| `update` | upstream 본문이 바뀌어 갱신함 (`fetched`도 갱신) |
| `meta` | 본문은 그대로고 `manifest.json`의 제목·요약·카테고리만 반영함 |
| `unchanged` | 원문과 동일 — 파일을 건드리지 않음 |
| `fail` | 404 또는 네트워크 오류. **기존 사본은 보존되고 나머지 문서는 계속 처리된다** |

문서 하나가 404여도 중단되지 않는다. 다만 실패가 있으면 **종료 코드 1**을 반환하므로 조용히 넘어가지 않는다. 404는 대개 upstream에서 페이지 이름이 바뀐 것이니, 새 슬러그를 찾아 `manifest.json`을 고친다.

### 문서 추가·제거

`manifest.json`의 `docs` 배열을 편집하고 `sync.py`를 실행한다.

```json
{
  "slug": "agent-sdk/sessions",
  "path": "agent-sdk/sessions.md",
  "category": "mcp-build",
  "title": "원문 제목 그대로",
  "summary": "한국어 요약 — 이 문서에서 MCP 관점으로 무엇을 얻을 수 있는지"
}
```

`summary`는 스크립트가 만들지 않는다. 추가할 때 문서를 읽고 직접 쓴다. manifest에서 항목만 지우면 파일은 남으므로, 제외할 문서는 파일도 함께 지운다. 추가 후보를 찾는 방법은 README.md의 "새 문서가 생겼는지 다시 확인하려면" 참고.

### 갱신 시점

정해진 주기는 없다. MCP 서버 구현 중 문서와 실제 동작이 어긋날 때, Claude Code 메이저 업데이트 후, `https://code.claude.com/docs/en/whats-new`에 MCP 관련 항목이 올라왔을 때 돌린다.
