# MCP 테스트 서버 로깅 설계

**목표:** 서버가 남기지 않던 로그를 파일로 남기고, 최대 3일 보관하며, 관리 화면에서 실시간으로 본다.

**배경:** 현재 서버는 로그를 전혀 남기지 않는다. `print()` 네 줄과 uvicorn의 stdout이 전부인데, `/mcp-test:server-start`가 백그라운드로 띄우므로 그 stdout은 아무 데도 가지 않는다. 서버가 죽으면 이유를 알 방법이 없다.

**대상 저장소:** `plugins/mcp-test/server/`

---

## 1. 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 로그 목적 | 크래시 원인 + 도구 호출 이력 + HTTP 접근 로그 + 관리 화면 실시간 보기 (전부) |
| 토큰 | 마스킹해서 남긴다 |
| 로그 경로 설정 | `--log-dir` > `$MCP_TEST_LOG_DIR` > `~/.claude/settings.json` > 기본값 |
| 보관 | 나이 기준 72시간 (개수 기준 아님) |
| 관리 화면 | SSE 스트리밍 |

---

## 2. 로그 형식

한 줄에 하나. JSON이 아니라 `grep`으로 읽는 줄이다.

```
2026-07-25T14:03:11Z INFO  http     POST /mcp 200 dur_ms=12 instance=a1b2c3d4 subject=al…(sha256:2bd806c9)
2026-07-25T14:03:11Z INFO  call     tool=echo instance=a1b2c3d4 dur_ms=3 ok
2026-07-25T14:03:40Z WARN  http     POST /mcp 401 dur_ms=0 reason=blank-token
2026-07-25T14:05:02Z INFO  registry blocked instance=a1b2c3d4
2026-07-25T14:09:55Z ERROR app      unhandled exception in serve()
Traceback (most recent call last):
  ...
```

| 필드 | 규격 |
|---|---|
| 타임스탬프 | `%Y-%m-%dT%H:%M:%SZ`, **UTC**, 주입된 `clock()`에서 |
| 레벨 | 5칸 좌측 정렬 (`DEBUG`, `INFO `, `WARN `, `ERROR`) |
| 범주 | 로거 이름의 마지막 마디, 8칸 좌측 정렬 |
| 본문 | 자유 형식. 관례상 `key=value` |

`WARN`은 `logging.WARNING`의 표시명 `WARNING`이 아니다. 포매터에서 매핑한다.

### 2.1 로거

루트는 `mcp_test_server`. 자식 넷.

| 로거 | 남기는 것 |
|---|---|
| `mcp_test_server.http` | 메서드, 경로, 상태, 소요 ms, instance, subject(마스킹), 거부 사유 |
| `mcp_test_server.call` | 도구 이름, instance, 소요 ms, 성공/예외 |
| `mcp_test_server.registry` | 연결, 차단/해제, purge 결과 |
| `mcp_test_server.app` | 기동, 종료, 크래시 트레이스백 |

registry 행에 있던 "stale 전이"는 뺐다. `is_stale()`은 `now`와 `last_seen`으로 그때그때 계산하는 파생값이라 "전이"라고 부를 사건 자체가 없다. 남기려면 `Registry`가 이전 상태를 들고 비교해야 하는데, 그 상태를 더하는 것은 로그 한 줄이 주는 값에 비해 과하다.

### 2.2 uvicorn 흡수

두 `uvicorn.Config` 모두에 다음을 준다.

- `log_config=None` — uvicorn이 자기 핸들러를 설치하지 못하게 한다. 그러면 `uvicorn.error` 로거가 루트로 전파되어 우리 핸들러에 잡힌다.
- `access_log=False` — 접근 로그는 §5의 `AccessLogMiddleware`가 양쪽 앱에 대해 일관된 형식으로 남긴다. uvicorn의 것과 이중으로 남기지 않는다.
- `log_level`은 지금 값을 유지한다 (MCP `info`, 관리 `warning`).

- `timeout_graceful_shutdown` — 양쪽 모두에 준다. 관리 앱의 SSE(§6.5)와 MCP의 streamable-http 알림 스트림은 스스로 끝나지 않으므로, 이 값이 없으면 관리 화면을 열어 둔 채 Ctrl-C를 눌렀을 때 프로세스가 영영 종료되지 않는다.

`log_config=None`이어도 uvicorn은 레벨을 설정한다. `uvicorn.Config.__init__`이 자기 `configure_logging()`을 불러 `uvicorn.error`/`uvicorn.access`/`uvicorn.asgi`의 레벨을 자기 `log_level`로 직접 박기 때문이다. 그래서 부모인 `uvicorn` 로거에 `setLevel()`을 걸어도 소용이 없고(자식 레벨이 명시돼 있다), 관리 쪽 `Config(log_level="warning")`가 MCP 쪽보다 나중에 만들어지므로 `uvicorn.error`는 WARNING에 고정된다 — 기동 안내도 `Waiting for connections to close...`도 파일에 남지 않는다.

**그래서 `logsetup`이 아니라 `serve()`가, `build_servers()` 호출 *직후에* `logging.getLogger("uvicorn.error").setLevel(logging.INFO)`을 건다.** `Config` 생성자가 레벨을 덮어쓰므로 그보다 뒤여야만 효과가 있다. 대가는 두 가지이고 그대로 받아들인다: 범주 칸이 `uvicorn.error`의 마지막 마디인 `error`로 찍히고(INFO 줄에도), uvicorn의 기동 안내가 `serve()`가 남기는 기동 줄과 거의 겹친다.

---

## 3. 파일과 보관

### 3.1 파일명

```
<log_dir>/mcp-test-server.<port>.<YYYY-MM-DD>.log
```

예: `~/.mcp-test-server/logs/mcp-test-server.8765.2026-07-25.log`

- `<port>`는 **MCP 리스너 포트**다. CLI가 `--port`로 여러 인스턴스를 지원하는데 기본 로그 디렉토리는 하나이고, 파일 핸들러는 멀티프로세스 안전하지 않다.
- `<YYYY-MM-DD>`는 **UTC 날짜**다.

### 3.2 날짜 경계 처리

`DailyFileHandler(logging.FileHandler)`가 담당한다.

- 매 `emit()`에서 `clock().date()`를 현재 파일의 날짜와 비교한다. 다르면 스트림을 닫고 새 파일을 연다.
- **판단 근거는 주입된 `clock`이지 `record.created`가 아니다.** 이 프로젝트에는 "시간을 쓰는 코드는 `clock`을 주입받는다"는 전역 제약이 있고(`app.py`의 `_purge_loop(registry, clock)`), stdlib의 `TimedRotatingFileHandler`는 자기 시계를 써서 이 제약을 만족할 수 없다.

### 3.3 왜 stdlib 핸들러를 쓰지 않는가

`logging.handlers.TimedRotatingFileHandler`의 `getFilesToDelete()`는 파일명을 정렬해 **개수** 기준으로 자른다(stdlib 소스 확인). 요구사항은 **나이** 기준이라 세 가지가 어긋난다.

1. 서버를 일주일 꺼 뒀다 켜면 10일 된 파일 3개가 그대로 남는다.
2. 삭제는 회전이 일어날 때만 돈다. 서버가 조용하면 아예 실행되지 않는다.
3. 시계를 주입할 수 없어 테스트에서 시간을 앞당길 수 없다.

### 3.4 보관 청소

`purge_logs(log_dir, now, max_age_seconds=259200, keep=<현재 열린 파일 경로 또는 None>)`

포트를 받지 않는다. 이 기계에 남은 이 서버의 로그를 포트와 무관하게 모두 청소하기 때문이다.

- 대상은 **`mcp-test-server.*.log` 글롭에 맞는 파일만**, 비재귀. `log_dir`은 사용자가 지정할 수 있으므로 무관한 파일을 지우면 안 된다. 홈 디렉토리를 가리켜도 안전해야 한다.
- 기준은 `mtime < now - 72h`.
- **현재 열려 있는 파일은 어떤 경우에도 지우지 않는다.**
- 다른 포트의 파일도 대상에 포함한다. 이 기계에 남은 이 서버의 로그를 모두 청소한다.
- 실행 시점: 기동 직후 한 번, 그리고 기존 `_purge_loop`가 도는 10분마다. `_purge_loop`는 이미 `clock`을 받고 있다.
- 삭제 실패(권한 등)는 WARN 한 줄. 루프를 중단하지 않는다.

---

## 4. 로그 경로 해석

### 4.1 우선순위

```
1. --log-dir <path>                                        (CLI 플래그)
2. $MCP_TEST_LOG_DIR                                       (환경변수)
3. ~/.claude/settings.json
     → pluginConfigs["mcp-test@*"].options.log_dir         (플러그인 설정)
4. ~/.mcp-test-server/logs                                 (기본값)
```

3번의 근거: `settings.md:816-834`에 따르면 Claude Code는 플러그인의 **비민감** `userConfig` 값을 사용자 `settings.json`의 `pluginConfigs[<plugin-id>].options`에 직접 쓴다. `log_dir`은 비민감이므로 여기 있다. (`auth_token`은 `sensitive: true`라 Keychain으로 가므로 이 경로로는 읽을 수 없다.)

사용자가 편집하는 곳은 **플러그인 설정 다이얼로그 하나**다. 중계 파일도, 훅도 없다.

### 4.2 플러그인 ID 매칭

플러그인 ID는 `<plugin-name>@<marketplace-name>` 형태다. 이 저장소의 마켓플레이스 이름은 `basic-mcp-py-server`이므로 보통 `mcp-test@basic-mcp-py-server`이지만, 서버는 자기가 어느 마켓플레이스에서 설치됐는지 알 수 없다. 그래서 **`mcp-test@` 접두사로 매칭한다.**

### 4.3 실패 모드

서버가 소유하지 않은 파일을, 스스로 알아낼 수 없는 키로 읽는다. 그래서 전부 명시한다.

| 상황 | 동작 |
|---|---|
| `~/.claude/settings.json` 없음 | 다음 우선순위로. 로그 없음 (정상 상황) |
| JSON 파싱 실패 | 다음 우선순위로. WARN 한 줄 |
| `pluginConfigs` 키 없음 | 다음 우선순위로. 로그 없음 |
| `mcp-test@*` 매치 0개 | 다음 우선순위로. 로그 없음 (설치했으나 미설정) |
| 매치 2개 이상 | 키를 정렬해 첫 번째. **어느 것을 골랐는지 WARN** |
| 키는 있으나 `options`가 없거나 `{}` | 다음 우선순위로. 로그 없음. "매치했으나 비었다"를 실패로 취급하지 않는다 (설치 후 이 항목만 미설정한 정상 상태) |
| `options.log_dir` 없음 / `null` | 다음 우선순위로 |
| 값이 빈 문자열 또는 공백뿐 | 유효한 경로가 아님. 다음 우선순위로. WARN 한 줄 |
| 값이 문자열이 아님 | 다음 우선순위로. WARN 한 줄 |
| 경로에 `~` 포함 | `expanduser()`로 확장. 상대 경로는 절대 경로로 변환 |

### 4.4 디렉토리를 쓸 수 없을 때

**파일 로깅만 포기하고 서버는 뜬다.**

- 디렉토리 생성 실패, 또는 파일 열기 실패 → stderr에 한 줄 안내, 파일 핸들러 없이 계속 진행.
- SSE 스트림과 stdout은 계속 동작한다. 스트림은 파일을 거치지 않으므로 영향이 없다(§6).
- `/api/status`의 `log_file`은 `null`이 되고, 관리 화면 로그 영역은 "파일 로깅이 꺼져 있다"고 표시한다.

이유: `--log-dir`는 이제 `ensure_port_free`와 같은 기동 시퀀스에 들어간다. 그 설계는 포트 실패를 트레이스백이 아니라 깔끔한 메시지로 만든 것이었다. 로그 디렉토리 때문에 테스트 서버가 뜨지 않는 것은 그 의도와 반대다.

### 4.5 플러그인 설정 항목

`plugins/mcp-test/.claude-plugin/plugin.json`의 `userConfig`에 추가한다.

```json
"log_dir": {
  "type": "string",
  "title": "서버 로그 디렉토리",
  "description": "비워 두면 ~/.mcp-test-server/logs 를 쓴다. 이 값은 서버가 기동할 때 읽으므로, 바꾸면 서버를 재기동해야 반영된다"
}
```

`type`은 `directory`가 아니라 `string`이다. `~`로 시작하는 값을 넣을 수 있어야 하고, 아직 없는 디렉토리도 지정할 수 있어야 하기 때문이다.

`default`는 넣지 않는다. 값이 없을 때의 기본값은 서버가 소유하며(§4.1의 4번), 양쪽에 같은 문자열을 두면 한쪽만 바뀌었을 때 조용히 어긋난다.

---

## 5. 요청 경로: 접근 로그와 401/403

### 5.1 왜 미들웨어를 하나 더 두는가

`AuthMiddleware`의 401/403 분기는 응답을 보내고 즉시 `return`한다. 그 안에서 상태 코드를 가로채는 방식으로 접근 로그를 만들면, **거부된 요청이 로그에 아예 남지 않는다.** 그런데 이 서버에서 가장 보고 싶은 줄이 바로 그것이다.

그래서 `AccessLogMiddleware`를 `AuthMiddleware` **바깥에** 둔다.

```
mcp_app   = AccessLogMiddleware(AuthMiddleware(mcp.streamable_http_app()))
admin_app = AccessLogMiddleware(build_admin_app(...))
```

`AuthMiddleware`가 401을 보낼 때 쓰는 `send`는 `AccessLogMiddleware`가 넘겨준 래퍼다. 따라서 거부 응답도 그대로 잡힌다. 덤으로 두 앱이 같은 형식의 접근 로그를 갖는다.

### 5.2 두 미들웨어의 계약

`AuthMiddleware`는 판단 결과를 스코프에 남긴다. ASGI 스펙상 구현체는 모르는 스코프 키를 무시하므로 안전하다.

```python
scope["mcp_test_auth"] = {
    "instance": str | None,
    "subject": str | None,     # 원본. 마스킹은 기록 시점에 한다
    "reason": str | None,      # "blank-token" | "blocked" | None
}
```

**이 키의 소유권:** 스키마는 이 절이 정의한다. `auth.py`가 쓰고 `access.py`가 읽는다. 한쪽을 바꾸는 것은 곧 양쪽을 바꾸는 것이다. 두 파일에 흩어진 매직 스트링이 아니라 두 모듈 사이의 계약이다.

`AccessLogMiddleware`는 호출이 끝난 뒤 이 값을 읽어 **한 줄만** 남긴다. 401/403에 두 줄이 나오지 않는다.

- 레벨: 2xx/3xx는 `INFO`, 4xx/5xx는 `WARN`
- `dur_ms`는 스코프 진입부터 **첫 응답 시작(`http.response.start`)**까지다. 응답 완료가 아니다.

  이 서버는 스트리밍 응답을 다룬다. `dur_ms`를 응답 완료 시점으로 재면 `/api/logs/stream` 같은 장수 연결은 **브라우저 탭이 닫힐 때까지 접근 로그가 아예 남지 않는다.** 대신 이 정의의 결과로, SSE 연결은 스트림이 열리는 순간 `dur_ms`가 0에 가까운 줄 하나를 남기고 그 뒤로 갱신되지 않는다. 이것이 의도한 동작이다.
- `scope["type"] != "http"`이면 즉시 위임한다. **`lifespan` 스코프가 그대로 통과해야 한다** — 이건 기존 `AuthMiddleware`와 같은 규칙이고, 어기면 인수 테스트 전부가 멈춘다.

### 5.3 토큰 마스킹

`mask_secret()`는 `auth.py`에 둔다. 토큰이 곧 `Identity`이고 그 모듈이 이미 그것을 소유한다.

```python
def mask_secret(value: str) -> str:
    """토큰을 로그에 적을 수 있는 형태로 바꾼다.

    같은 입력은 항상 같은 출력이므로 "이 두 요청은 같은 사람"을 추적할 수 있다.
    """
```

| 입력 | 출력 |
|---|---|
| `""` | `(empty)` |
| `"a"` | `a…(sha256:ca978112)` |
| `"alice"` | `al…(sha256:2bd806c9)` |

규칙: 앞 2글자(짧으면 있는 만큼) + `…(sha256:` + `sha256(value.encode("utf-8")).hexdigest()[:8]` + `)`.

**마스킹은 기록 시점(호출부)에서 한다.** 포매터가 정규식으로 훑는 방식은 새 필드가 생길 때마다 조용히 샌다.

### 5.4 이건 새로운 노출인가

아니다. 토큰은 이미 `sessions` 도구와 관리 화면을 통해 같은 서버에 붙은 모든 세션에 평문으로 보이고, `plugin.json`이 "진짜 자격 증명 말고 알아볼 수 있는 별명을 넣어라"라고 안내한다. 달라지는 것은 **메모리에서 사라지던 값이 최대 3일간 디스크에 남는다**는 점이며, 마스킹은 그 차이를 없앤다.

---

## 6. SSE 스트림

### 6.1 구조

로깅 핸들러에서 구독자 큐로 fan-out한다. **파일을 다시 읽지 않는다.** 따라서 파일 회전은 스트림과 무관하고, 파일 로깅이 꺼져 있어도 스트림은 동작한다.

```
로거 → BroadcastHandler.emit() ─┬→ 구독자 큐 1 → SSE 응답 1
                                └→ 구독자 큐 2 → SSE 응답 2
      → DailyFileHandler.emit() → 파일
```

### 6.2 이벤트 루프가 없을 수 있다

`configure_logging()`은 `asyncio.run()` **전에** 돈다. 기동 로그와 `PortInUse`는 루프가 생기기 전에 나고, 크래시 로그는 루프가 닫힌 뒤에 날 수 있다.

**규칙: 루프가 없거나 닫혀 있으면 스트림용으로는 조용히 버리고, 파일에는 쓴다.**

```python
def publish(self, line: str) -> None:
    loop = self._loop
    if loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(self._fanout, line)
    except RuntimeError:      # 호출 직전에 닫힌 경우
        return
```

루프는 `serve()`가 시작될 때 `bind_loop()`로 넘긴다. 이 규칙을 어기면 `logging` 안에서 예외가 나고, 그것은 stderr 잡음이 되거나 — `raiseExceptions=False`라면 — 이 기능의 존재 이유인 크래시 줄이 조용히 사라진다.

**루프가 닫히는 중일 때의 `RuntimeError`는 예외 상황이 아니라 정상이다.** `is_closed()`가 아직 `False`를 돌려준 직후에 `call_soon_threadsafe`가 `RuntimeError: Event loop is closed`를 던질 수 있다. 종료 시퀀스에서 흔히 일어나며, 삼켜야 한다. 같은 보호가 `_fanout` 콜백 경로에도 있어야 한다 — 그쪽은 이미 루프 안이지만, 구독자 큐가 정리된 뒤에 도착할 수 있다.

### 6.3 큐에는 포맷된 문자열을 넣는다

`LogRecord`는 `args`를 들고 있다가 나중에 `%` 보간을 한다. 그 "나중"이 다른 스레드/태스크가 되고 인자가 가변 객체이면 파일과 화면의 내용이 달라진다. **`emit()`에서 한 번 포맷하고, 그 문자열만 넘긴다.**

### 6.4 느린 구독자

구독자 큐는 `asyncio.Queue(maxsize=1000)`. 가득 차면 **가장 오래된 것부터 버린다**(`get_nowait()` 후 `put_nowait()`). 느린 브라우저가 서버를 세워서는 안 된다.

### 6.5 엔드포인트

`GET /api/logs/stream` → `text/event-stream`

- 각 줄은 `data: <포맷된 줄>\n\n`
- 15초마다 `: ping\n\n` 주석 하트비트. 유휴 연결이 끊기지 않게 한다.
- 연결이 끊기면 `finally`에서 구독 해제. 구독자 집합에 누수가 없어야 한다.

### 6.6 관리 화면

- 페이지 로드 시 **현재 로그 파일의 마지막 200줄**을 서버 렌더링으로 `<pre>`에 넣는다. 구현은 파일 끝에서 64KB를 읽어 줄로 자르고 뒤에서 200개를 취한다. 기존 관리 화면과 같이 모든 값을 `html.escape` 한다.
- 그 뒤부터 `EventSource`가 아래에 줄을 붙인다. 스크롤이 맨 아래에 있을 때만 자동으로 따라간다.
- 파일 로깅이 꺼져 있으면 백필 대신 "파일 로깅이 꺼져 있다"를 표시하고, 스트림은 그대로 동작한다.

### 6.7 `/api/status` 추가 필드

```json
{ "log_dir": "/Users/…/logs", "log_file": "/Users/…/logs/mcp-test-server.8765.2026-07-25.log" }
```

파일 로깅이 꺼져 있으면 둘 다 `null`. 나중에 다른 도구가 로그 위치를 알아야 할 때 구조를 뜯지 않게 하려는 자리다.

---

## 7. 크래시 경로

첫 번째 목적이 "서버가 죽은 이유"인데 **지금 그 경로가 없다.** `app.py:180`의 `asyncio.gather`에는 `finally: purge.cancel()`뿐이고, `__main__.main()`은 `PortInUse`와 `KeyboardInterrupt`만 잡는다. 나머지는 아무 데도 가지 않는 stdout으로 흘러간다.

핸들러를 붙이는 것으로는 해결되지 않는다. 세 곳을 고친다.

### 7.1 `main()` — `BaseException`

```python
except BaseException:
    logging.getLogger("mcp_test_server.app").exception("unhandled exception")
    raise
```

`Exception`이 아니라 `BaseException`이다. uvicorn은 바인딩에 실패하면 `sys.exit(1)`을 호출하고 `SystemExit`은 `BaseException`이다 — `app.py:78`의 주석이 이미 그 사실을 기록하고 있다. 기존 `PortInUse` / `KeyboardInterrupt` 분기는 그대로 두고, 그 뒤에 온다. 잡은 뒤 반드시 재발생시켜 종료 코드를 바꾸지 않는다.

### 7.2 `loop.set_exception_handler`

purge 태스크와 uvicorn의 커넥션별 태스크에서 난 예외는 `main()`까지 오지 않는다. `serve()` 시작 시 루프에 핸들러를 걸어 `mcp_test_server.app`에 `ERROR`로 남긴다.

### 7.3 종료 시 flush

방금 쓴 크래시 줄이 버퍼에 남은 채 프로세스가 끝나면 이 기능 전체가 의미를 잃는다. 두 겹으로 막는다.

- **주 경로:** `main()`의 `finally`에서 `logging.shutdown()`을 명시적으로 호출한다.
- **보조:** `atexit`에도 건다.

순서가 이렇게 되는 이유가 있다. `atexit` 핸들러는 인터프리터가 이미 정리를 시작한 뒤에 돈다. 그 시점에 `DailyFileHandler.emit()`이 주입된 `clock`을 부르는데(§3.2), 기본값인 `_utcnow`는 모듈 전역의 `datetime`을 참조한다. 전역이 이미 정리됐을 수 있다. `atexit`만 믿으면 안 된다.

### 7.4 크래시 경로를 실제로 증명하는 방법

**시그널로 죽이는 테스트는 아무것도 증명하지 않는다.** `test_acceptance.py`의 `_terminate_and_reap`은 `terminate()` — SIGTERM을 보내는데, 파이썬은 이를 기본적으로 잡지 않는다. 프로세스는 `finally`도 `atexit`도 실행하지 않고 즉시 끝난다. 그런 테스트는 통과해도 §7.3이 동작한다는 뜻이 아니다.

대신 **진짜 미처리 예외**로 죽인다. 테스트는 자식 프로세스를 이렇게 띄운다.

테스트는 `sys.executable -c <아래 코드>`로 자식을 띄운다. `log_dir`과 `port`는 `sys.argv[1:]`로 넘겨받으므로 문자열 보간이 필요 없다.

```python
import sys

import mcp_test_server.app as app
import mcp_test_server.__main__ as m


async def boom(**kwargs):
    raise RuntimeError("deliberate-crash-marker")


app.serve = boom
m.serve = boom
sys.exit(m.main(["--log-dir", sys.argv[1], "--port", sys.argv[2]]))
```

`__main__`이 `from .app import serve`로 이름을 끌어왔으므로 **양쪽 모듈 전역을 모두 바꿔야 한다.** 한쪽만 바꾸면 패치가 먹지 않고 서버가 정상 기동해 테스트가 멈춘다.

그리고 확인한다.

1. 프로세스가 0이 아닌 코드로 끝났다.
2. 넘겨준 디렉토리의 로그 파일에 `deliberate-crash-marker`와 `Traceback`이 둘 다 있다.

이것이 §7.1의 `except BaseException`, §7.3의 `finally` flush, 그리고 파일 핸들러가 실제 프로세스에서 함께 동작한다는 것을 증명한다. `except BaseException`을 지우거나 `finally`의 flush를 지우면 이 테스트는 실패해야 한다 — 구현 후 실제로 되돌려 확인한다.

---

## 8. 파일 구조

### 8.1 신규

| 파일 | 책임 |
|---|---|
| `logpaths.py` | 경로 해석(§4), 파일명 규칙(§3.1), 72시간 청소(§3.4). 전부 "파일시스템 + 이름" |
| `logsetup.py` | `DailyFileHandler`, 포매터, 로거 배선, uvicorn 흡수(§2, §3.2) |
| `logstream.py` | `LogBroadcaster`와 `BroadcastHandler`(§6.1–6.4) |
| `access.py` | `AccessLogMiddleware`(§5) |

`access.py`는 설계 논의 때의 3개에서 하나 늘어난 것이다. 이것은 요청 경로에서 도는 순수 ASGI 미들웨어라 "로깅 구성"(`logsetup`)과도 "파일시스템"(`logpaths`)과도 책임이 다르고, `auth.py`에 넣으면 그 모듈이 인증과 관측을 겸하게 된다. 두 앱이 공유하는 조각이므로 `app.py`에 인라인할 수도 없다.

### 8.2 수정

| 파일 | 무엇을 |
|---|---|
| `app.py` | 로깅 배선, `AccessLogMiddleware` 적용, `bind_loop`, `set_exception_handler`, `_purge_loop`에 로그 청소 추가, `build_stack`/`build_servers` 시그니처 확장 |
| `__main__.py` | `--log-dir` 플래그, `configure_logging()` 호출, `except BaseException` |
| `auth.py` | `mask_secret()`, `scope["mcp_test_auth"]` 기록 |
| `mcp_server.py` | 도구 호출 로그 |
| `admin.py` | 로그 영역과 백필, `/api/logs/stream`, `/api/status`의 `log_dir`·`log_file` |
| `.claude-plugin/plugin.json` | `log_dir` userConfig |
| `README.md` | 로그 위치, 설정 방법, 재기동 필요, 보관 기간, 마스킹 사실 |

---

## 9. 테스트

### 9.1 반드시 실패할 수 있어야 하는 것

일반적인 경로가 아니라, **놓치면 조용히 없는 채로 통과할** 것들이다. 각 테스트는 구현을 일부러 되돌려 실제로 실패하는지 확인한다.

| # | 확인 | 왜 이것이어야 하는가 |
|---|---|---|
| 1 | 빈 토큰 요청이 `WARN … 401 … reason=blank-token` 한 줄을 남긴다 | `AuthMiddleware`가 조기 `return`하므로 순진한 구현에서는 이 줄이 아예 생기지 않는다. 200 테스트의 부산물이 아니라 독립 테스트여야 한다 |
| 2 | **실행 중인 이벤트 루프 없이** emit한 레코드가 파일에 남는다 | 해피 패스 SSE 테스트로는 절대 잡히지 않는다. 기동·크래시 로그가 여기 걸린다. **이 테스트는 반드시 `async def`가 아닌 동기 함수여야 한다** — 이 저장소는 `asyncio_mode = "auto"`라 비동기 테스트에는 항상 실행 중인 루프가 있고, 그러면 아무것도 증명하지 못한다 |
| 3 | 가짜 시계를 자정 너머로 밀면 두 번째 파일이 생긴다 | 주입된 시계를 쓰는지 검증하는 유일한 방법 |
| 4 | 4일 전 mtime 파일은 지워지고 어제 것은 남는다 | 개수 기준과 나이 기준을 실제로 구분한다 |
| 5 | 청소가 `mcp-test-server.*.log`가 아닌 파일은 건드리지 않는다 | `log_dir`은 사용자가 지정한다. 홈 디렉토리를 가리켜도 안전해야 한다 |
| 6 | 관리 앱을 ASGI 게이트로 감쌌을 때 **스트림 본문이 클라이언트에 가지 않는다** | 기존 게이트 테스트는 "레지스트리 상태가 안 바뀐다"를 본다. 스트림의 실패 방식은 다르다 — 레지스트리를 건드리지 않고 내용만 샌다 |
| 7 | 별도 프로세스에서 **미처리 예외로** 죽은 서버의 로그 파일에 트레이스백이 있다 (§7.4의 방법) | flush와 예외 경로는 인프로세스 테스트로 증명되지 않는다. 그리고 **SIGTERM으로 죽이는 방식은 증명하지 못한다** — 파이썬이 잡지 않으므로 `finally`도 `atexit`도 돌지 않는다 |
| 8 | 쓸 수 없는 `--log-dir`를 줘도 서버가 뜨고 MCP가 응답한다 | §4.4가 지켜지는지 |

### 9.2 그 외

- `resolve_log_dir` 우선순위 4단계 각각, 그리고 §4.3 표의 모든 실패 모드
- `mask_secret`: 빈 문자열, 1글자, 같은 입력의 안정성, 다른 입력의 구분
- `LogBroadcaster`: 구독/해제, 큐가 가득 찰 때 오래된 것부터 버림, 연결 종료 후 구독자 집합에 누수 없음
- `AccessLogMiddleware`: `lifespan` 스코프 통과, 200 경로, `dur_ms` 존재
- SSE 엔드포인트: `Content-Type`이 `text/event-stream`, 로그 발생 시 한 줄이 나옴
- 관리 화면: 백필 200줄, 파일 로깅이 꺼졌을 때의 표시, `html.escape` 적용

---

## 10. 범위 밖

- 로그 레벨을 런타임에 바꾸는 기능. 필요하면 `--log-level`을 나중에 추가한다.
- 로그 검색/필터링 UI. 브라우저의 `Ctrl+F`로 충분하다.
- 구조화 로그(JSON) 출력. 지금은 사람이 읽는 용도다.
- 이미 떠 있는 서버의 로그 경로 변경. 기동 시에만 읽는다.
- 크기 기준 회전과 전체 용량 상한. 나이 기준 72시간만 지킨다.
