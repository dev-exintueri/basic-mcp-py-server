# basic-mcp-py-server

## MCP 지식의 출처 (docs/claude-base/)

Claude Code가 MCP를 어떻게 다루는지에 관한 판단은 **추측하거나 기억에 의존하지 말고 `docs/claude-base/`를 먼저 읽는다.** 이 디렉토리는 공식 문서의 미러이므로 근거로 인용할 수 있다.

- 진입점은 [docs/claude-base/README.md](docs/claude-base/README.md)의 "어디부터 읽나"와 [manifest.json](docs/claude-base/manifest.json)의 한국어 `summary`다. 20개 문서를 전부 열지 말고 여기서 해당 파일을 고른다.
- 도구 이름·권한·설정·연결 실패·SDK 계약처럼 문서에 답이 있는 주제는 웹 검색보다 이쪽이 먼저다.
- 단, MCP **프로토콜 규격**(JSON-RPC, 수명주기, capability)은 여기 없다. 그건 https://modelcontextprotocol.io 소관이다.

### 참조 전 신선도 확인 (3일)

위 문서를 참조하려는 시점에 [docs/claude-base/last-sync.txt](docs/claude-base/last-sync.txt)의 `last run:` 날짜를 오늘과 비교한다. **3일 이상 지났으면 읽기 전에 전체를 갱신한다.**

```bash
python3 docs/claude-base/sync.py
```

- 세션 시작마다 돌리지 않는다. MCP 지식이 실제로 필요한 턴에만 확인한다.
- 실행 후 `.md` 파일이 바뀌었다면 그것이 곧 upstream 변경분이다. 조용히 커밋하지 말고 무엇이 바뀌었는지 사용자에게 보고한다.
- `sync.py`는 실패가 하나라도 있으면 **종료 코드 1**이다. 404는 슬러그가 바뀐 것이니 `manifest.json`을 고쳐야 한다 — 넘어가지 않는다.
- 갱신 방식과 표시(`new`/`update`/`meta`/`unchanged`/`fail`)의 뜻은 [docs/claude-base/CLAUDE.md](docs/claude-base/CLAUDE.md)에 있다.

## 질문 기록 (docs/qna/)

사용자가 프롬프트 첫머리에 `질문:` 또는 `[질문]`을 붙인 경우, **답변한 그 턴에 이어서 묻지 않고** 내용을 `docs/qna/`에 저장한다.

- **표시가 없는 일반 의문문은 저장하지 않는다.** 판단 기준은 오직 이 마커의 유무다.
- 세션 끝이나 다음 턴으로 미루지 않는다. `/clear`나 컨텍스트 요약으로 유실된다.
- `docs/qna/`가 없으면 만든다.
- 파일명은 `YYYY-MM-DD-질문요지-케밥.md`. 같은 이름이 있으면 뒤에 `-2`를 붙인다.
- 같은 흐름의 후속 질문은 새 파일을 만들지 말고 기존 파일에 이어 쓴다.

형식은 다음과 같다. 본문은 한국어로 쓴다.

```markdown
---
date: 2026-07-25
question: 질문 원문 한 줄
---

## 질문
(원문 그대로)

## 답변
(핵심부터. 답변 당시 결론을 남기는 것이 목적이므로 다시 쓰지 말고 그대로 옮긴다)

## 근거
- `path/to/file.py:42` — 확인한 내용
- https://... — 참고한 문서
```
