# 같은 계약을 지키는 Node.js 서버를 나란히 둔다

**목표:** 파이썬 MCP 테스트 서버와 **밖에서 구별되지 않는** Node.js 서버를 만들고, 어느 쪽을 띄울지 `/mcp-test:server-start` 에서 고른다.

**왜:** 이 저장소는 학습용이고 다른 프로젝트의 base 예시다. 같은 계약을 두 생태계에서 어떻게 달성하는지 나란히 놓고 읽을 수 있으면, 무엇이 MCP 의 요구이고 무엇이 파이썬의 사정인지 갈라진다.

---

## 1. 전제 — 클라이언트는 런타임을 모른다

`.mcp.json` 의 서버 항목은 **하나**로 유지한다. 두 서버는 같은 `8765`/`8766` 을 쓰고 **배타적으로** 뜬다.

항목을 둘로 늘리지 않는 이유는 두 가지다.

- 도구 이름이 서버 키에서 파생된다. 항목을 늘리면 `mcp__plugin_mcp-test_test-server__ping` 옆에 두 번째 이름 공간이 생기고, README 에 적힌 권한 규칙이 전부 어긋난다.
- Claude Code 는 세션 시작마다 두 항목에 모두 붙으려 한다. 안 뜬 쪽은 매번 연결 실패로 표시된다.

**런타임 선택은 기동 시점에만 존재한다.** 이것이 "동일하게 동작"의 조작적 정의이자, 이 설계에서 가장 먼저 깨지면 안 되는 것이다.

## 2. 배치

```
plugins/mcp-test/
├── .mcp.json              변경 없음
├── .claude-plugin/        변경 없음
├── commands/server-start.md   런타임 인자
├── hooks/check-server.sh      안내 문구
├── scripts/connection-id.sh   변경 없음
├── server/                기존 파이썬 (admin.py 만 수정)
├── server-node/           신규
└── conformance/           신규 — 공유 적합성 스위트
```

기존 `server/` 를 `servers/python/` 으로 옮기지 않는다. 이름의 대칭보다 기존 경로를 건드리지 않는 쪽을 택했다 — `server-start.md`, README 의 `uv run --directory`, 훅 경로가 전부 딸려 온다.

**툴체인:** TypeScript + express + vitest, 빌드는 `tsc` → `dist/`. MCP SDK 는 **v1.x 계열**(`@modelcontextprotocol/sdk`)을 쓴다. 2.0 은 `@modelcontextprotocol/server` + `/node` 로 분리됐지만 아직 `2.0.0-alpha.2` 이므로 예시 저장소에 넣지 않는다.

## 3. 패리티 계약

"관찰 가능한 경계는 동일하다" 는 그대로 두면 거짓이다. 지킬 수 없는 항목이 있다. 계약의 실체는 아래 두 표이고, **적합성 스위트가 강제하는 것은 첫 번째 표뿐이다.**

### 3.1 계약한다

| 항목 | 계약 내용 |
|---|---|
| 로그 타임스탬프 | `%Y-%m-%dT%H:%M:%SZ`. 밀리초 없음 — Node 의 `toISOString()` 은 `.789Z` 를 붙이므로 잘라내야 한다 |
| 레벨·카테고리 폭 | `{레벨:<5} {카테고리:<8}` 좌측 정렬. `WARNING`→`WARN`, `CRITICAL`→`ERROR` |
| 우리 카테고리 | `http`, `call`, `registry`, `app` 이 **존재하고** 아래 형식을 지킨다. 이 넷이 카테고리의 전부라는 뜻은 아니다 — §3.2 참조 |
| 토큰 마스킹 | 앞 두 글자 + `…`(U+2026, 마침표 세 개가 아니다) + `(sha256:앞8자리)` |
| 접근 로그 필드 (`http`) | `<메서드> <경로> <상태> dur_ms=N`, 있을 때만 `instance=` `subject=` `reason=`. 400 이상은 WARN |
| 도구 호출 로그 (`call`) | 성공 `tool=<이름> instance=<id> dur_ms=<N> ok` |
| 레지스트리 로그 (`registry`) | `connected instance=<id> subject=<마스킹> label=<label>`, `block instance=<id>`, `unblock instance=<id>` |
| 접근 로그 시점 | 응답 **시작**. SSE 연결도 열리는 순간 `dur_ms≈0` 줄 하나를 남기고 갱신되지 않는다 |
| 줄 이스케이프 | 조립이 끝난 한 줄에 캐리지 리턴과 줄바꿈을 한 번 건다 |
| 응답 상태 | 401(빈 토큰) / 403(차단) / 404(모르는 연결 ID) / 303(HTML 폼 리다이렉트), 오류 응답의 `error` 키 존재 |
| MCP 엔드포인트 | `/mcp` 의 POST·GET·DELETE |
| 도구 | `ping` `echo` `whoami` `sessions` 의 이름, 필수 인자의 이름과 타입, 출력 키. **JSON Schema 전체를 비교하지 않는다** — FastMCP 와 TS SDK 가 내는 스키마는 `title` 같은 부수 필드에서 갈릴 수 있다 |
| 기동 로그 | 기동 시 `app` 카테고리로 줄 하나. 문구는 계약하지 않는다 |
| `session_view` | 키 10개(`instance_id` `subject` `project` `label` `mcp_session_id` `connected_at` `last_seen` `call_count` `blocked` `stale`)와 각 타입 |
| 관리 라우트 | `/`, `/api/status`, `/fragments/sessions`, `/api/logs/stream`, `/api/sessions/{id}/block`, `/api/sessions/{id}/unblock` |
| 로그 파일명 | `mcp-test-server.<포트>.<날짜>.log`, 날짜 롤오버 |
| 로그 경로 우선순위 | `--log-dir` > `$MCP_TEST_LOG_DIR` > `~/.mcp-test-server/logs`. **`settings.json` 층은 여기 없다** — §3.2 참조 |
| 보관 스윕 | mtime 기준, `mcp-test-server.*.log` 패턴만, 비재귀, 열린 파일 제외 |
| CLI 플래그 | `--host --port --admin-port --stale-after --log-dir --log-retention-days`, 그리고 `--log-retention-days 0` 거부 |
| 노출 경고 | 루프백 밖 바인딩 시 stderr 경고 |

### 3.2 계약하지 않는다

| 항목 | 이유 |
|---|---|
| 오류 메시지의 한국어 문구 | 파이썬 쪽 문구를 다듬으면 노드가 깨진다. 상태 코드와 `error` 키만 본다 |
| **카테고리 집합 전체** | 아래 참조 |
| 관리 페이지 HTML 전체 | CSS·공백·스크립트는 제외. `/fragments/sessions` 가 **같은 열 제목과 이스케이프된 같은 값**을 담는 것만 본다 |
| `ping.pid` 의 값 | 값이 아니라 타입만 본다 |
| 내부 파일 구성 | 노드는 노드 관용구를 따른다. 파일 이름·개수·분할을 맞추지 않는다 |
| 도구 실패 로그의 `error=` | 파이썬은 예외 **클래스 이름**을 적는다(`_logged`). 두 언어의 예외 이름이 같을 이유가 없다. WARN 레벨과 `tool=` `instance=` `dur_ms=` 까지만 본다 |
| `settings.json` 의 `log_dir` 층 | 아래 참조 |

**카테고리 집합을 계약에서 뺀 이유.** 파이썬 서버를 실제로 띄워 로그를 받아 보면 우리 카테고리 넷 말고도 이런 줄이 섞인다.

```
2026-07-26T01:35:31Z INFO  error    Uvicorn running on http://127.0.0.1:18765 (Press CTRL+C to quit)
2026-07-26T01:35:31Z INFO  streamable_http_manager StreamableHTTP session manager started
2026-07-26T01:35:36Z WARN  transport_security Missing Content-Type header in POST request
```

핸들러를 **루트 로거**에 붙이기 때문이다(`logsetup.py`). uvicorn 과 파이썬 MCP SDK 가 자기 로거로 내는 줄이 그대로 딸려 온다. `streamable_http_manager` 는 8칸 정렬도 넘긴다.

Node SDK 가 같은 이름의 카테고리를 낼 이유가 없다. 그래서 **"이 네 카테고리가 존재한다"만 계약하고 "카테고리가 이 넷뿐이다"는 계약하지 않는다.** 스위트는 우리 줄을 찾을 때 카테고리로 필터링하고, 모르는 카테고리가 섞여 있어도 실패하지 않아야 한다.

기동 줄도 마찬가지다. `app` 카테고리 기동 줄 하나는 계약하되(§3.1), 그 앞뒤로 프레임워크가 무엇을 더 찍든 보지 않는다.

**`settings.json` 층을 계약에서 뺀 이유.** `logpaths.py` 는 이 경로를 `Path.home()/".claude"/"settings.json"` 으로 하드코딩하고, 주입 지점은 `resolve_log_dir(settings_path=...)` 라는 **파이썬 함수 인자뿐**이다. 적합성 스위트는 CLI 와 HTTP 로만 서버를 몬다 — 진짜 `~/.claude/settings.json` 에 쓰지 않고는 이 층을 건드릴 수 없다.

계약해 놓고 검증할 수 없는 항목을 표에 남겨 두지 않는다. 이 층은 **각 런타임의 자기 단위 테스트**가 덮는다. 노드도 같은 우선순위와 같은 키 경로(`pluginConfigs["mcp-test@*"].options.log_dir`)를 구현하되, 그 사실은 스위트가 아니라 `server-node/tests/` 가 보증한다.

나중에 이 층까지 스위트로 옮기고 싶으면 두 런타임에 `MCP_TEST_SETTINGS_PATH` 같은 주입 통로를 함께 내면 된다. 지금 만들지 않을 뿐, 길을 막지는 않는다.

### 3.3 파이썬 쪽 변경

`/api/status` 응답에 `"runtime": "python"` 을 더한다. 노드는 `"node"` 를 낸다.

401 프로브로는 어느 런타임이 답했는지 알 수 없다. 이 필드가 없으면 기동 충돌 안내도 `/mcp-test:server-status` 도 런타임을 말할 수 없다. **이 변경 때문에 이 작업은 순수 추가가 아니다.**

## 4. 런타임 선택 UX

`/mcp-test:server-start` 는 인자를 **항상 요구한다.** 기본값을 두지 않는다 — 비교가 목적인 저장소에서 한쪽이 기본이면 다른 쪽은 부록이 된다.

| 입력 | 동작 |
|---|---|
| 인자 없음 | `python` 과 `node` 중 무엇을 띄울지 되묻는다 (`$ARGUMENTS` 가 비어 있는 경우) |
| 알 수 없는 값 | 두 런타임 이름을 알리고 멈춘다 |
| `python` | `uv run --directory ${CLAUDE_PLUGIN_ROOT}/server mcp-test-server` |
| `node` | `node ${CLAUDE_PLUGIN_ROOT}/server-node/dist/main.js` |

이미 떠 있으면 `/api/status` 의 `runtime` 을 읽어 **어느 런타임이 pid 몇으로 떠 있는지** 알리고 멈춘다. 다른 런타임으로 바꾸려면 먼저 내리라고 안내한다.

## 5. 적합성 스위트

```
plugins/mcp-test/conformance/
├── pyproject.toml     pytest, httpx, mcp (클라이언트용)
├── conftest.py        --target 플래그, 서버 기동 픽스처
├── test_mcp.py        슬라이스 1
├── test_admin.py      슬라이스 2
└── test_logging.py    슬라이스 3
```

pytest 로 쓴다. `server/tests/test_acceptance.py` 에 서버를 subprocess 로 띄우고 포트 준비를 기다리고 종료하며 로그를 회수하는 코드(`free_port`, `_port_ready`, `_terminate_and_reap`)가 이미 있어서 옮겨 재활용한다.

`server/tests/` 안에 두지 않는다. 거기 있으면 "파이썬 서버의 테스트" 로 읽히고 `server/pyproject.toml` 의 `testpaths = ["tests"]` 와도 얽힌다. 별도 `pyproject.toml` 을 두고 `uv run --directory plugins/mcp-test/conformance pytest --target=<런타임>` 으로 돈다.

### 5.1 거짓 초록을 막는 장치

이 스위트에서 가장 위험한 실패는 빨간색이 아니라 **틀린 초록**이다.

| 위험 | 막는 방법 |
|---|---|
| `dist/` 가 낡았거나 없다 | 픽스처가 노드를 띄우기 **전에** `npm run build` 를 돌리고, 실패하면 거기서 멈춘다. 그러지 않으면 어제 코드를 통과시키고 초록을 보고한다 |
| 툴체인이 없다 | `--target=node` 인데 `node_modules` 가 없으면 **실패**한다. skip 은 요약 줄에서 "덮었다" 로 읽힌다 |
| 로그 디렉토리 오염 | 실행마다 `--log-dir` 로 임시 디렉토리를 준다. 그러지 않으면 슬라이스 3 이 상대 런타임이 남긴 줄을 읽는다 |
| 포트 충돌 | 실행마다 빈 포트를 잡는다. 사용자가 띄워 둔 서버에 붙어 검증하는 일이 없어야 한다 |

## 6. 노드 구현에서 조용히 깨지는 것들

파이썬 쪽이 "깨면 안 되는 것" 으로 못 박아 둔 성질 중 셋이 express 에서 **기본값대로 하면** 깨진다. 셋 다 오류를 내지 않는다.

**접근 로그는 인증 미들웨어 바깥이다.** express 에서 "바깥" 은 **먼저 등록**이다. `app.use(accessLog)` 가 `app.use(bearerAuth)` 보다 앞에 와야 한다. 뒤집으면 401/403 요청이 로그에 남지 않는다 — 이 서버에서 가장 보고 싶은 줄이 그것이다. (`server/src/mcp_test_server/access.py` 모듈 독스트링)

**로그는 응답 완료가 아니라 시작에서 남긴다.** express 관용구인 `res.on('finish')` 는 여기서 틀렸다. `/api/logs/stream` 은 SSE 라 브라우저 탭이 닫힐 때까지 finish 하지 않으므로, 그 엔드포인트는 접근 로그가 한 줄도 남지 않는다. `res.writeHead` 를 감싸 첫 바이트에서 남긴다.

**`express.json()` 은 POST 에만 건다.** GET(SSE 스트림)까지 걸면 transport 가 읽어야 할 스트림이 소진된다. MCP SDK 의 `handleRequest(req, res, body)` 는 POST 에서만 파싱된 본문을 받는다.

**인자 없는 도구의 콜백은 `(extra)` 하나만 받는다.** SDK 의 `executeToolHandler` 는 `inputSchema` 유무로 갈린다 — 있으면 `(args, extra)`, 없으면 **`(extra)`**. 파이썬 FastMCP 는 `ctx: Context` 파라미터로 주입하므로 규약이 다르다. `ping` `whoami` `sessions` 는 인자가 없으므로 `(extra) => ...` 이고, 습관대로 `(_args, extra)` 라고 쓰면 `extra` 가 첫 인자에 들어가 **`whoami` 가 연결 ID 를 조용히 놓친다.** 오류는 나지 않는다.

헤더는 `extra.requestInfo.headers` 에서 **소문자 키**로 읽는다.

**`createMcpExpressApp()` 을 쓰지 않는다.** SDK 가 제공하는 이 헬퍼는 host 가 `127.0.0.1` 일 때 DNS 리바인딩 보호(Host 헤더 검증)를 자동으로 건다. 파이썬 서버에는 없는 동작이라 그만큼 두 런타임이 갈린다. 순수 `express()` 를 쓴다.

**노드 transport 는 stateful 이어야 한다.** `sessionIdGenerator: () => randomUUID()` 를 준다. SDK 예제에 자주 보이는 `sessionIdGenerator: undefined`(stateless)를 쓰면 세션 ID 가 발급되지 않아 `session_view.mcp_session_id` 가 영원히 null 이 된다 — 계약한 필드의 타입이 뒤집히고 DELETE 경로도 성립하지 않는다.

그리고 파이썬에는 없던 몫이 하나 생긴다. **세션별 transport 라우팅.** 파이썬은 `mcp.streamable_http_app()` 이 내부에서 처리하지만, 노드는 `Map<mcpSessionId, transport>` 를 직접 관리해야 한다. 이것은 `Registry` 와 별개다 — `Registry` 는 `X-Client-Instance` 로 세는 우리 개념이고, transport Map 은 MCP 프로토콜의 `Mcp-Session-Id` 로 도는 SDK 사정이다. **둘을 섞지 않는다.**

## 7. 주석 규약

`CLAUDE.md` 의 `## 응용할 때` 규약을 **노드 모듈에도 적용한다.** 파일 머리 JSDoc 블록에 절을 둔다. 포크해서 쓰는 사람에게는 런타임이 무엇이든 같은 지도가 필요하다.

검사는 `server-node/tests/commentConventions.test.ts` 로 만든다. 파이썬 쪽은 `ast` 로 독스트링을 읽지만, 노드는 정규식으로 파일 머리 블록 주석을 본다.

`CLAUDE.md` 에 이 규약이 두 런타임 모두에 적용됨을 명시한다.

## 8. 함께 바꿔야 하는 것

| 파일 | 변경 |
|---|---|
| `server/src/mcp_test_server/admin.py` | `/api/status` 에 `runtime` 필드 |
| `commands/server-start.md` | 인자 없으면 되묻기, 충돌 시 런타임 명시 |
| `hooks/check-server.sh` | 서버가 없을 때 안내 문구에 두 런타임을 적는다 |
| `README.md` | 기동 절차, 개발 절차, 수동 검증 체크리스트 |
| `CLAUDE.md` | 주석 규약의 적용 범위 |

`server/tests/test_admin.py` 는 `/api/status` 필드 추가에 따라 함께 본다.

## 9. 구현 순서

세 슬라이스. 각 슬라이스가 **스위트 작성 → 파이썬 통과 확인 → 노드 구현 → 노드 통과** 다.

스위트가 먼저 파이썬을 통과해야 하므로, 스위트 자체의 버그와 노드의 미구현이 섞이지 않는다.

| 슬라이스 | 범위 |
|---|---|
| 1. MCP 핵심 | `/mcp`, 도구 4개, 401/403, 레지스트리, `X-Client-*` 헤더, 세션별 transport 라우팅 |
| 2. 관리 API | `/api/status`(+`runtime`), `/fragments/sessions`, block/unblock, 인덱스 페이지 |
| 3. 로깅 | 줄 형식 세 종류(`http` `call` `registry`), 카테고리, 마스킹, 파일명·롤오버, 경로 우선순위(스위트는 3단계, `settings.json` 층은 노드 단위 테스트), 보관 스윕, SSE 스트림, 접근 로그 시점 |

슬라이스 1 이 끝나면 노드에서 `ping` 이 도는 것을 눈으로 확인할 수 있다. 중단해도 안전한 지점이 슬라이스 경계마다 있다.

## 10. 이번 범위 밖 — 기록해 두는 부채

`server/tests/test_plugin_files.py` 와 `test_marketplace.py` 는 런타임 중립이다. 플러그인 배포 산출물(`.mcp.json`, 훅, 마켓플레이스 카탈로그, README)을 검증하는데 파이썬 서버 디렉토리 안에 산다. 노드가 들어오면 이 비대칭이 더 눈에 띈다.

**이번에는 옮기지 않는다.** 옮기면 `PLUGIN_ROOT = parents[2]` 같은 경로 상수가 전부 따라오고, 이 작업의 목적과 무관한 변경이 섞인다. 부채로 남긴다.
