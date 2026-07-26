# 포크해서 쓰는 사람을 위한 주석 체계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 11개 모듈 독스트링에 `## 응용할 때` 절을 더하고, 그 방식을 `CLAUDE.md` 규칙으로 남긴다.

**Architecture:** 코드 동작은 한 줄도 바꾸지 않는다. 산출물은 (1) 모듈 독스트링의 응용 축, (2) 여섯 곳의 주석 보강, (3) `CLAUDE.md` 규칙, (4) 그 절이 빠지는 것을 잡는 메타 테스트 하나다. 메타 테스트는 파일을 `import` 하지 않고 `ast` 로 읽으므로 모듈 수준 부작용이 없다.

**Tech Stack:** Python 3.11+, pytest, `ast` (표준 라이브러리)

**설계 스펙:** `docs/superpowers/specs/2026-07-26-forking-comments-design.md`

## Global Constraints

- **선행 조건 1 — `docs/superpowers/plans/2026-07-26-log-retention-flag.md` 를 먼저 구현한다.** 그 계획은 `__main__.py`·`app.py`·`README.md` 를 정확한 스니펫 매칭으로 고친다. 주석이 먼저 들어가면 어긋난다
- **선행 조건 2 — 워킹 트리를 먼저 비운다.** `admin.py` / `tests/test_admin.py` 에 완결된 미커밋 변경(`_SESSION_POLL_MS`)이 있다. 커밋하지 않으면 아래 모든 태스크의 `git diff` 검증이 오염된다
- **줄 번호를 믿지 않는다.** 이 계획과 스펙의 줄 번호는 커밋 `4b31412` 시점의 것이다. **매 편집 전에 파일을 열어 위치를 다시 찾는다.** 이 작업 자체가 모든 모듈의 독스트링을 늘려 아래 줄을 계속 밀어낸다
- **코드 동작을 바꾸지 않는다.** 최종 diff 는 주석·독스트링·`CLAUDE.md`·새 테스트 파일뿐이어야 한다. 리팩터링, 이름 변경, "지나가다 보인" 수정 금지
- **자명한 멤버에는 독스트링을 붙이지 않는다.** `registry.py` 의 `get`/`all`/`remove`/`block`/`is_blocked` 등은 그대로 둔다. "모든 함수에 주석" 은 이 작업이 아니다
- **주석에서 코드를 줄 번호로 가리키지 않는다.** 파일 이름과 심볼 이름으로 가리킨다
- **독스트링 안에 백슬래시를 쓰지 않는다.** 파이썬 독스트링에서 `\r` 은 실제 캐리지 리턴이 된다. "캐리지 리턴과 줄바꿈" 처럼 풀어 쓴다
- **`git add` 에 경로를 명시한다.** `git add -A` / `git add .` 금지
- **모든 명령은 `plugins/mcp-test/server` 에서 실행한다** (아래 `cd` 포함)

## 파일 구조

| 파일 | 책임 | 변경 |
|---|---|---|
| `plugins/mcp-test/server/tests/test_comment_conventions.py` | 규약 중 기계가 볼 수 있는 부분 검사 | **신규** |
| `.../src/mcp_test_server/mcp_server.py` | 도구 정의 — 포크한 사람이 가장 먼저 여는 파일 | 독스트링 + 주석 |
| `.../src/mcp_test_server/registry.py` | 세션 상태 | 독스트링 |
| `.../src/mcp_test_server/auth.py` | 인증·신원 | 독스트링 |
| `.../src/mcp_test_server/admin.py` | 관리 화면 | 독스트링 + 주석 |
| `.../src/mcp_test_server/app.py` | 조립·기동 | 독스트링 |
| `.../src/mcp_test_server/logpaths.py` | 로그 경로·청소 | 독스트링 + 주석 |
| `.../src/mcp_test_server/logsetup.py` | 로깅 구성 | 독스트링 + 스펙 경로 |
| `.../src/mcp_test_server/__main__.py` | CLI | 독스트링 |
| `.../src/mcp_test_server/access.py` | 접근 로그 | 독스트링 |
| `.../src/mcp_test_server/logstream.py` | SSE fan-out | 독스트링 |
| `.../src/mcp_test_server/__init__.py` | 패키지 진입점 — 전체 지도 | 독스트링 |
| `CLAUDE.md` | 프로젝트 규칙 | 절 추가 |

---

### Task 1: 메타 테스트 그물과 코어 5개 모듈의 응용 축

**Files:**
- Create: `plugins/mcp-test/server/tests/test_comment_conventions.py`
- Modify: `.../src/mcp_test_server/mcp_server.py` (모듈 독스트링)
- Modify: `.../src/mcp_test_server/registry.py` (모듈 독스트링)
- Modify: `.../src/mcp_test_server/auth.py` (모듈 독스트링)
- Modify: `.../src/mcp_test_server/admin.py` (모듈 독스트링)
- Modify: `.../src/mcp_test_server/app.py` (모듈 독스트링)

**Interfaces:**
- Produces: `tests/test_comment_conventions.py` 의 `SRC`, `SECTION`, `_docstring(path)`, `_module_paths()` — Task 2 가 이 헬퍼를 그대로 쓰고 대상 목록만 넓힌다
- Produces: 각 모듈 독스트링 끝의 `## 응용할 때` 절. Task 2 가 같은 형식을 따른다

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/mcp-test/server/tests/test_comment_conventions.py` 를 새로 만든다.

```python
"""주석 규약 중 기계가 볼 수 있는 부분을 검사한다.

내용의 질은 사람이 본다. 여기서 잡는 것은 절이 통째로 빠지는 경우 —
특히 새 모듈을 만들면서 `## 응용할 때` 를 빠뜨리는 것이다. 그 절은
포크한 사람이 이 파일에서 무엇을 해도 되는지 아는 유일한 통로이므로,
없으면 모듈이 하나 늘 때마다 지도에 빈칸이 생긴다.

파일을 import 하지 않고 ast 로 읽는다. import 하면 모듈 수준 부작용이
테스트에 딸려 온다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mcp_test_server"
SECTION = "## 응용할 때"

# Task 2 에서 이 목록을 패키지 전체 순회로 넓힌다.
_CORE = ("mcp_server.py", "registry.py", "auth.py", "admin.py", "app.py")


def _module_paths() -> list[Path]:
    return sorted(SRC.glob("*.py"))


def _docstring(path: Path) -> str | None:
    return ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))


def test_source_directory_is_where_we_think_it_is() -> None:
    # 경로가 어긋나면 아래 테스트들이 빈 목록을 돌며 조용히 통과한다.
    assert (SRC / "app.py").is_file()
    assert len(_module_paths()) >= 11


@pytest.mark.parametrize("name", _CORE)
def test_core_modules_document_how_to_extend_them(name: str) -> None:
    doc = _docstring(SRC / name)
    assert doc is not None, f"{name} 에 모듈 독스트링이 없다"
    assert SECTION in doc, f"{name} 의 독스트링에 '{SECTION}' 절이 없다"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd plugins/mcp-test/server && uv run pytest tests/test_comment_conventions.py -v
```

Expected: `test_source_directory_is_where_we_think_it_is` 는 PASS. `test_core_modules_document_how_to_extend_them` 5개가 전부 FAIL — `AssertionError: mcp_server.py 의 독스트링에 '## 응용할 때' 절이 없다`.

- [ ] **Step 3: `mcp_server.py` 독스트링 교체**

파일 맨 위 `"""FastMCP 인스턴스와 노출 도구 4개."""` 를 아래로 바꾼다.

```python
"""FastMCP 인스턴스와 노출 도구 4개.

## 응용할 때

**바꿔도 되는 것.** 도구를 더하고 빼는 곳은 `build_mcp()` 안이다. 함수를
쓰고 데코레이터 두 개를 얹으면 끝이다. `FastMCP("mcp-test-server")` 의
이름은 이 프로세스 안에서만 쓰인다 — 로그 파일명(`logpaths` 의
`LOG_GLOB`)이나 플러그인 ID 와 연결되지 않으므로 자유롭게 바꾼다.

**깨면 안 되는 것.** `@mcp.tool()` 이 위, `@_logged` 가 아래여야 한다.
FastMCP 의 `tool()` 은 함수를 등록한 뒤 **받은 함수를 그대로 돌려주므로**,
순서를 뒤집으면 서버에 등록되는 것은 원본이고 `_logged` 가 감싼 것은
아무도 부르지 않는 사본이 된다. 도구는 멀쩡히 동작하고 호출 로그만
사라진다 — 오류는 나지 않는다.
"""
```

- [ ] **Step 4: `registry.py` 독스트링에 절 추가**

`"""세션 레지스트리. 이 프로세스의 유일한 상태 보유자다."""` 를 바꾼다.

```python
"""세션 레지스트리. 이 프로세스의 유일한 상태 보유자다.

## 응용할 때

**바꿔도 되는 것.** `SessionRecord` 의 필드와 `session_view()` 의 출력이
이 서버가 세션에 대해 무엇을 아는지 정한다. 자기 도메인에 맞게 가장
먼저 고칠 곳이다.

**함께 바꿔야 하는 것.** 필드를 늘리면 두 곳이 따라온다 — 값을 어디서
얻는가(`auth` 의 `Identity` 와 `touch()` 호출), 화면에 어떻게 보이는가
(`admin` 의 `_ROW` 와 `_SESSIONS` 의 열 제목).

**깨면 안 되는 것.** 아래 `Registry` 독스트링의 전제다. 레코드를 읽은 뒤
고치기까지 사이에서 `await` 하지 않는다. 비동기 메서드를 더하고 싶으면
락부터 도입한다.
"""
```

- [ ] **Step 5: `auth.py` 독스트링 끝에 절 추가**

기존 독스트링(`"""인증·차단 미들웨어와 요청 신원 파싱.` 로 시작)의 **마지막 줄과 닫는 `"""` 사이**에 아래를 넣는다. 기존 문단은 지우지 않는다.

```python
## 응용할 때

**바꿔도 되는 것.** `read_identity()` 의 통과 조건이 이 서버의 인증
전부다. 진짜 인증을 넣는다면 여기다 — 토큰을 대조하든 JWT 를 검증하든,
`Identity` 를 돌려주거나 `None` 을 돌려주기만 하면 나머지는 그대로
동작한다. 읽는 헤더 이름과 `UNKNOWN_INSTANCE` 같은 기본값도 바꿀 수 있다.

**함께 바꿔야 하는 것.** 헤더 이름을 바꾸면 플러그인 쪽 `.mcp.json` 의
`headers` 와 `scripts/connection-id.sh` 가 따라온다. `Identity` 에 필드를
더하면 `registry` 의 `touch()` 도 따라온다.

**깨면 안 되는 것.** `AUTH_SCOPE_KEY` 로 스코프에 넣는 딕셔너리의 키
세 개는 `access` 와의 계약이다. 그리고 이 미들웨어는 순수 ASGI 여야
한다 — `BaseHTTPMiddleware` 로 바꾸면 응답을 감싸게 되어 스트리밍
응답과 얽힌다.
```

- [ ] **Step 6: `admin.py` 독스트링 끝에 절 추가**

기존 독스트링의 마지막 문단(`증명한다.` 로 끝난다) 뒤, 닫는 `"""` 앞에 넣는다.

```python
## 응용할 때

**바꿔도 되는 것.** `_PAGE` / `_SESSIONS` / `_ROW` 템플릿과 라우트 목록이
관리 화면의 전부다. 폴링 주기(`_SESSION_POLL_MS`)와 하트비트 간격도
여기 있다.

**깨면 안 되는 것.**

- 템플릿은 `str.format()` 으로 렌더한다. 그래서 CSS 와 자바스크립트의
  중괄호가 전부 이중이다. 새 스타일이나 스크립트를 넣을 때 이걸 놓치면
  `KeyError` 로 페이지가 통째로 500 이 된다.
- 세션에서 온 값은 반드시 `html.escape()` 를 거쳐 넣는다. 그 값들은
  클라이언트가 정한다.
- `log_stream` 의 `should_stop()` 검사와 그 `return` 을 지우면 정상
  종료마다 ERROR 트레이스백이 남는다. 아래 본문 주석에 이유가 있다.
```

- [ ] **Step 7: `app.py` 독스트링 교체**

`"""두 ASGI 앱을 조립하고 한 프로세스에서 함께 기동한다."""` 를 바꾼다.

```python
"""두 ASGI 앱을 조립하고 한 프로세스에서 함께 기동한다.

## 응용할 때

**바꿔도 되는 것.** `DEFAULTS` 의 포트와 유휴 기준, 그리고
`build_stack()` 이 무엇을 무엇으로 감싸는지. 미들웨어를 더한다면 거기다.

**깨면 안 되는 것.**

- `AccessLogMiddleware` 가 `AuthMiddleware` **바깥**이어야 한다. 안으로
  넣으면 401/403 으로 거부된 요청이 로그에 남지 않는다 — 이 서버에서
  가장 보고 싶은 줄이 그것이다.
- 관리 리스너의 주소는 `ADMIN_HOST` 고정이다. 인증이 없는 리스너이므로
  바꿀 수 있는 통로를 만들지 않는다.
- `uvicorn.error` 레벨을 되돌리는 줄은 `build_servers()` 뒤여야 한다.
  이유는 그 줄의 주석에 있다.
- 두 리스너는 같은 이벤트 루프를 공유한다. 이것이 `registry` 의 락 없는
  설계가 성립하는 근거다. 별도 프로세스나 스레드로 쪼개려면 거기부터
  다시 봐야 한다.
"""
```

- [ ] **Step 8: 테스트 통과 확인**

```bash
cd plugins/mcp-test/server && uv run pytest tests/test_comment_conventions.py -v
```

Expected: 6개 전부 PASS.

- [ ] **Step 9: 전체 테스트 통과 확인**

```bash
cd plugins/mcp-test/server && uv run pytest
```

Expected: 전체 PASS. 주석만 바꿨으므로 하나라도 깨지면 독스트링 문법을 잘못 닫았거나 코드를 건드린 것이다.

- [ ] **Step 10: 커밋**

```bash
git add \
  plugins/mcp-test/server/tests/test_comment_conventions.py \
  plugins/mcp-test/server/src/mcp_test_server/mcp_server.py \
  plugins/mcp-test/server/src/mcp_test_server/registry.py \
  plugins/mcp-test/server/src/mcp_test_server/auth.py \
  plugins/mcp-test/server/src/mcp_test_server/admin.py \
  plugins/mcp-test/server/src/mcp_test_server/app.py
git commit -m "docs(comments): 자주 고치는 다섯 모듈에 응용 축을 적는다"
```

---

### Task 2: 나머지 여섯 모듈과 전체 순회 검사

**Files:**
- Modify: `.../tests/test_comment_conventions.py` (대상을 패키지 전체로)
- Modify: `.../src/mcp_test_server/logpaths.py`, `logsetup.py`, `__main__.py`, `access.py`, `logstream.py`, `__init__.py`

**Interfaces:**
- Consumes: Task 1 의 `SRC`, `SECTION`, `_docstring()`, `_module_paths()`
- Produces: 패키지의 **모든** `.py` 가 `## 응용할 때` 를 갖는다는 불변식. 이후 새 모듈은 자동으로 이 검사에 걸린다

- [ ] **Step 1: 검사 대상을 패키지 전체로 넓힌다 (테스트 먼저)**

`tests/test_comment_conventions.py` 에서 `_CORE` 상수와 `test_core_modules_document_how_to_extend_them` 을 **삭제하고**, 그 자리에 아래를 넣는다. 파일 위쪽 헬퍼(`SRC`, `SECTION`, `_module_paths`, `_docstring`)와 `test_source_directory_is_where_we_think_it_is` 는 그대로 둔다.

```python
_MODULES = _module_paths()


@pytest.mark.parametrize("path", _MODULES, ids=[p.name for p in _MODULES])
def test_every_module_documents_how_to_extend_it(path: Path) -> None:
    """새 모듈을 만들면서 이 절을 빠뜨리는 것을 잡는다."""
    doc = _docstring(path)
    assert doc is not None, f"{path.name} 에 모듈 독스트링이 없다"
    assert SECTION in doc, f"{path.name} 의 독스트링에 '{SECTION}' 절이 없다"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd plugins/mcp-test/server && uv run pytest tests/test_comment_conventions.py -v
```

Expected: Task 1 에서 고친 5개는 PASS, 나머지 6개(`logpaths.py`, `logsetup.py`, `__main__.py`, `access.py`, `logstream.py`, `__init__.py`)가 FAIL.

- [ ] **Step 3: `logpaths.py` 독스트링 끝에 절 추가**

기존 독스트링(`남긴다.` 로 끝난다) 뒤, 닫는 `"""` 앞에 넣는다.

```python
## 응용할 때

**바꿔도 되는 것.** `DEFAULT_LOG_DIR`, `log_file_name()` 의 형식,
`MAX_AGE_SECONDS` 기본값.

**함께 바꿔야 하는 것.**

- `LOG_GLOB` 과 `log_file_name()` 은 한 쌍이다. 한쪽만 바꾸면 청소가
  아무것도 찾지 못해 로그가 영영 쌓인다 — 오류는 나지 않는다.
- `_PLUGIN_ID_PREFIX` 는 플러그인 쪽 `.claude-plugin/plugin.json` 의
  `name` 과 맞물린다. 어긋나면 `log_dir` 플러그인 설정을 조용히 못 읽고
  기본 경로로 떨어진다.

**깨면 안 되는 것.** `purge_logs` 가 `LOG_GLOB` 에 맞는 파일만, 비재귀로
보는 것. `log_dir` 은 사용자가 정하므로 홈 디렉토리를 가리킬 수도 있다 —
패턴을 넓히거나 재귀로 바꾸면 남의 파일을 지운다.
```

- [ ] **Step 4: `logsetup.py` 독스트링 끝에 절 추가**

기존 독스트링(`오염된다.` 로 끝난다) 뒤, 닫는 `"""` 앞에 넣는다.

```python
## 응용할 때

**바꿔도 되는 것.** `ClockFormatter.format()` 의 줄 형식과 `_LEVEL_NAMES`,
`configure_logging()` 의 기본 레벨.

**함께 바꿔야 하는 것.** 줄 형식을 바꾸면 관리 화면의 로그 패널과
`logpaths.tail_lines()` 백필이 그 형식을 그대로 보여주므로 함께 본다.

**깨면 안 되는 것.**

- 핸들러는 루트 로거에 붙인다. 패키지 로거로 옮기면 uvicorn 의 줄이
  파일에 남지 않는다.
- `configure_logging()` 은 `__main__.main()` 에서만 부른다.
- `DailyFileHandler.emit()` 이 회전 실패를 삼키고 상태를 나중에 옮기는
  순서. 여기서 예외가 새면 로그 실패가 요청 처리를 통째로 죽인다.
```

- [ ] **Step 5: `__main__.py` 독스트링 교체**

`"""CLI 진입점."""` 을 바꾼다.

```python
"""CLI 진입점.

## 응용할 때

**바꿔도 되는 것.** CLI 인자. 새 인자는 `parse_args()` 에 더하고
`serve()` 로 넘긴다.

**깨면 안 되는 것.**

- 경로 해석 경고는 로깅이 준비된 **뒤에** 남긴다. 경로를 정하는 동안에는
  남길 곳이 없다.
- `except BaseException` 은 오타가 아니다. uvicorn 이 바인딩에 실패하면
  `sys.exit()` 를 부르고 그 `SystemExit` 은 `Exception` 이 아니다.
- `finally` 의 `logging.shutdown()` 을 지우지 않는다. `atexit` 만으로는
  늦다 — 그때는 핸들러가 참조하는 모듈 전역이 이미 사라졌을 수 있다.
"""
```

- [ ] **Step 6: `access.py` 독스트링 끝에 절 추가**

기존 독스트링(`갖게 한다.` 로 끝난다) 뒤, 닫는 `"""` 앞에 넣는다. **백슬래시를 쓰지 않는다.**

```python
## 응용할 때

포크해도 대개 그대로 둔다. 고친다면 `_log()` 가 어떤 필드를 남기는지
정도다.

**깨면 안 되는 것.**

- 이 미들웨어는 `AuthMiddleware` 바깥에 선다 (`app` 의 `build_stack()`).
  안으로 옮기면 거부된 요청이 로그에 남지 않는다.
- 캐리지 리턴과 줄바꿈 이스케이프는 조립이 끝난 한 줄에 한 번 건다.
  필드마다 거는 방식으로 바꾸면 새 필드가 생길 때 조용히 샌다.
- 로그는 응답이 **시작**될 때 남긴다. 완료로 옮기면 SSE 같은 장수 연결이
  끊길 때까지 아무 줄도 남지 않는다.
```

- [ ] **Step 7: `logstream.py` 독스트링 끝에 절 추가**

기존 독스트링(`동작한다.` 로 끝난다) 뒤, 닫는 `"""` 앞에 넣는다.

```python
## 응용할 때

포크해도 대개 그대로 둔다. 고친다면 `max_queue` 정도다.

**깨면 안 되는 것.**

- 큐에는 `LogRecord` 가 아니라 포맷된 문자열을 넣는다. 이유는
  `BroadcastHandler` 독스트링에 있다.
- `publish()` 는 루프가 없거나 닫히는 중이면 조용히 버린다. 여기서
  예외를 내면 이 기능의 존재 이유인 크래시 줄이 사라진다.
- 큐가 가득 차면 오래된 것부터 버린다. 느린 브라우저가 서버를 세우면
  안 된다.
```

- [ ] **Step 8: `__init__.py` 를 전체 지도로 만든다**

`"""MCP 테스트 서버."""` 를 바꾼다. 이 파일이 포크한 사람이 처음 여는 곳이다.

```python
"""MCP 테스트 서버. 여러 Claude Code 세션이 한 프로세스에 붙는다.

## 어디부터 읽나

| 모듈 | 하는 일 |
|---|---|
| `app` | 두 ASGI 앱을 조립하고 함께 기동한다. 전체 그림은 여기 |
| `mcp_server` | 도구 정의. 자기 도구를 더할 곳 |
| `registry` | 세션 상태. 이 프로세스의 유일한 상태 보유자 |
| `auth` | 인증과 신원 파싱, 차단 |
| `access` | 요청 하나당 접근 로그 한 줄 |
| `admin` | 관리 화면과 그 API |
| `logpaths` `logsetup` `logstream` | 로그 경로·구성·SSE fan-out |
| `__main__` | CLI 진입점 |

## 응용할 때

이 저장소는 base 로 쓰라고 있다. **모듈마다 독스트링 끝에 `## 응용할 때`
절이 있고, 거기에 그 파일에서 바꿔도 되는 것과 깨면 안 되는 것이 적혀
있다.** 고치려는 파일의 그 절부터 읽는다.

가장 자주 고치는 곳은 `mcp_server` 의 `build_mcp()`(도구), `registry` 의
`SessionRecord`(무엇을 기억하는가), `auth` 의 `read_identity()`(인증)다.

이름을 바꿀 때 짝이 되는 것들은 `logpaths` 의 응용 절에 정리돼 있다.
"""
```

- [ ] **Step 9: 테스트 통과 확인**

```bash
cd plugins/mcp-test/server && uv run pytest tests/test_comment_conventions.py -v
```

Expected: 11개 모듈 전부 PASS (+ 경로 확인 테스트 1개).

- [ ] **Step 10: 전체 테스트 통과 확인**

```bash
cd plugins/mcp-test/server && uv run pytest
```

Expected: 전체 PASS.

- [ ] **Step 11: 커밋**

```bash
git add \
  plugins/mcp-test/server/tests/test_comment_conventions.py \
  plugins/mcp-test/server/src/mcp_test_server/logpaths.py \
  plugins/mcp-test/server/src/mcp_test_server/logsetup.py \
  plugins/mcp-test/server/src/mcp_test_server/__main__.py \
  plugins/mcp-test/server/src/mcp_test_server/access.py \
  plugins/mcp-test/server/src/mcp_test_server/logstream.py \
  plugins/mcp-test/server/src/mcp_test_server/__init__.py
git commit -m "docs(comments): 나머지 모듈까지 응용 축을 채우고 검사를 전체로 넓힌다"
```

---

### Task 3: 밀도 보강 여섯 곳

**Files:**
- Modify: `.../src/mcp_test_server/logsetup.py` (스펙 참조 세 곳)
- Modify: `.../src/mcp_test_server/mcp_server.py` (`_logged` 독스트링)
- Modify: `.../src/mcp_test_server/admin.py` (`_PAGE` 위, `_toggle` 독스트링)
- Modify: `.../src/mcp_test_server/logpaths.py` (`_clean` 독스트링)

**Interfaces:**
- Consumes: Task 1·2 가 넣은 독스트링. 이 태스크는 본문 주석만 건드린다

**설계 근거:** 스펙 §4. 여섯 곳 중 `__init__.py` 는 Task 2 Step 8 에서 이미 처리했으므로 여기서는 다섯 곳이다.

- [ ] **Step 1: `logsetup.py` 의 스펙 참조에 문서 경로를 넣는다**

세 곳이 `"스펙 §2"`, `"스펙 §3.3"`, `"스펙 §4.4"` 만 적고 **어느 문서인지 밝히지 않는다.** 대상은 `docs/superpowers/specs/2026-07-25-server-logging-design.md` 이고 절 번호는 유효하다(각각 "로그 형식", "왜 stdlib 핸들러를 쓰지 않는가", "디렉토리를 쓸 수 없을 때").

모듈 독스트링 끝(Task 2 에서 넣은 `## 응용할 때` 절 **앞**)에 아래 한 문단을 넣는다.

```python
아래 주석의 "스펙 §N" 은 전부
`docs/superpowers/specs/2026-07-25-server-logging-design.md` 를 가리킨다.
```

그러면 개별 참조는 그대로 둬도 추적된다.

- [ ] **Step 2: `mcp_server.py` 의 `_logged` 독스트링에 순서 이유를 더한다**

기존 독스트링의 문단 뒤, 닫는 `"""` 앞에 넣는다.

```python
    이 데코레이터는 `@mcp.tool()` **아래**에 온다. `tool()` 은 등록만 하고
    받은 함수를 그대로 돌려주므로, 위아래를 바꾸면 등록되는 것은 원본이고
    이 래퍼는 아무도 부르지 않는다.
```

- [ ] **Step 3: `admin.py` 의 템플릿 위에 이중 중괄호 이유를 적는다**

`_PAGE = """<!doctype html>` **바로 위** 줄에 넣는다.

```python
# 아래 세 템플릿은 str.format() 으로 렌더한다. 그래서 CSS 와 자바스크립트의
# 중괄호가 전부 이중이다 — 하나라도 홑겹으로 두면 format() 이 그것을 치환
# 자리로 읽고 KeyError 를 내 페이지가 통째로 500 이 된다.
```

- [ ] **Step 4: `admin.py` 의 `_toggle` 에 독스트링을 붙인다**

`def _toggle(action: str) -> Callable[[Request], object]:` 바로 아래에 넣는다.

```python
        """block 과 unblock 라우트를 같은 코드로 만든다.

        두 핸들러는 부르는 레지스트리 메서드만 다르다. 클로저로 만들면
        `action` 이 로그 문구와 응답에도 그대로 쓰여 두 경로가 갈라지지
        않는다.
        """
```

- [ ] **Step 5: `logpaths.py` 의 `_clean` 에 독스트링을 붙인다**

`def _clean(value: str) -> Path:` 바로 아래에 넣는다.

```python
    """사용자가 준 경로 문자열을 한 형태로 정규화한다.

    이 값은 세 곳에서 온다 — CLI 플래그, 환경 변수, `settings.json`. 셋 다
    사람이 손으로 적는 자리라 `~/logs` 같은 물결표와 상대 경로가 섞여
    들어온다. 절대 경로로 맞춰 두면 로그에 찍히는 경로가 일관되고,
    `purge_logs` 가 열려 있는 파일을 건너뛸 때 하는 경로 비교도 성립한다.
    """
```

- [ ] **Step 6: 스펙 참조가 실제 절을 가리키는지 대조**

```bash
grep -n '^### 3.3\|^## 2\.\|^### 4.4' docs/superpowers/specs/2026-07-25-server-logging-design.md
```

Expected: `## 2. 로그 형식`, `### 3.3 왜 stdlib 핸들러를 쓰지 않는가`, `### 4.4 디렉토리를 쓸 수 없을 때` 세 줄이 나온다. 하나라도 다르면 Step 1 의 문구를 고치지 말고 **어긋난 참조 자체를 고친다.**

- [ ] **Step 7: 전체 테스트 통과 확인**

```bash
cd plugins/mcp-test/server && uv run pytest
```

Expected: 전체 PASS.

- [ ] **Step 8: 커밋**

```bash
git add \
  plugins/mcp-test/server/src/mcp_test_server/logsetup.py \
  plugins/mcp-test/server/src/mcp_test_server/mcp_server.py \
  plugins/mcp-test/server/src/mcp_test_server/admin.py \
  plugins/mcp-test/server/src/mcp_test_server/logpaths.py
git commit -m "docs(comments): 추적되지 않는 스펙 참조와 함정 다섯 곳을 적는다"
```

---

### Task 4: `CLAUDE.md` 에 주석 규칙을 남긴다

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1~3 이 만든 실제 사례. 규칙은 그것을 명문화한 것이지 새 발명이 아니다

- [ ] **Step 1: `CLAUDE.md` 끝에 절을 추가한다**

`## 질문 기록 (docs/qna/)` 절 **뒤**, 파일 맨 끝에 붙인다.

````markdown
## 코드 주석

이 저장소의 코드는 **포크해서 자기 MCP 서버를 만드는 데 쓰인다.** 주석은
그 독자를 위해 쓴다.

### 무엇을 쓰나

- **모듈 독스트링** — 이 파일의 목적 한 줄, 그리고 이 파일에서 가장
  비자명한 성질. 예: `access.py` 는 왜 `AuthMiddleware` 바깥에 서는지,
  `registry.py` 는 왜 락이 없는지.
- **함수 독스트링** — 무엇을 하는지에 더해 **왜 이 모양인지.** 왜 따로
  떼어냈는지(`app.py` 의 `build_servers`), 왜 미리 확인하는지(`app.py` 의
  `ensure_port_free`), 상태를 바꾸는 순서가 왜 중요한지(`logsetup.py` 의
  `DailyFileHandler.emit`).
- **인라인 `#`** — "이건 틀린 것처럼 보이는데 아니다" 에만 쓴다. 예:
  `auth.py` 의 DELETE 분기가 왜 먼저 갈라지는지, `app.py` 의
  `uvicorn.error` 레벨 복원이 왜 그 자리인지, `access.py` 의 이스케이프가
  왜 조립된 줄에 한 번만 걸리는지.

### 무엇을 쓰지 않나

- **자명한 멤버에는 독스트링을 붙이지 않는다.** `registry.py` 의
  `get`/`all`/`remove`/`block` 이 그렇다. 이름이 이미 답이면 침묵이 옳다.
  **"모든 함수에 주석" 은 이 규칙이 아니다.**
- 코드를 그대로 옮겨 적지 않는다.

### `## 응용할 때`

모듈 독스트링 **끝에** 이 절을 둔다. 포크한 사람이 이 파일에서 무엇을 할
수 있는지 알려주는 자리다. 세 축으로 쓰고 해당 없는 축은 생략한다.

1. **바꿔도 되는 것**
2. **바꾸면 함께 바꿔야 하는 것** — 짝이 되는 다른 파일을 적는다
3. **깨면 안 되는 것** — 어기면 조용히 망가지는 불변식

만질 일이 없는 파일이면 그렇다고 적는다. 그것도 정보다.

**새 모듈을 만들면 이 절도 함께 쓴다.** 빠뜨리면
`tests/test_comment_conventions.py` 가 잡는다.

### 언어와 인용

- 한국어로 쓴다. 코드 식별자는 원형 그대로 둔다.
- 설계 문서를 인용할 때는 **파일 경로와 절 번호를 함께** 적는다.
  `스펙 §4.4` 만으로는 어느 문서인지 알 수 없다.
- **주석에서 코드를 줄 번호로 가리키지 않는다.** 파일 이름과 심볼
  이름으로 가리킨다. 줄 번호는 다음 편집에 낡는데, 낡았다는 사실이
  드러나지 않아 읽는 사람을 엉뚱한 곳으로 보낸다. 예외는 **시점이 고정된
  기록** 이다 — 커밋 메시지, 설계 문서, `docs/qna/` 의 근거 줄.
- 파이썬 독스트링 안에 백슬래시를 쓰지 않는다. `\r` 은 글자가 아니라
  실제 캐리지 리턴이 된다. "캐리지 리턴" 처럼 풀어 쓴다.
````

- [ ] **Step 2: 규칙이 자기 원칙을 지키는지 확인**

방금 추가한 절만 본다. 파일 전체를 grep 하면 안 된다 — 기존 `## 질문 기록` 절의 형식 예시에 `path/to/file.py:42` 라는 **가상 경로**가 있고, 그것은 규칙 위반이 아니다(질문 기록은 시점이 고정된 스냅샷이다).

```bash
awk '/^## 코드 주석/,0' CLAUDE.md | grep -nE '\.py:[0-9]+'
```

Expected: **아무것도 나오지 않는다** (종료 코드 1). 하나라도 나오면 방금 쓴 "줄 번호로 가리키지 않는다" 를 스스로 어긴 것이니, 그 줄을 심볼 이름으로 고친다.

- [ ] **Step 3: 전체 테스트 통과 확인**

```bash
cd plugins/mcp-test/server && uv run pytest
```

Expected: 전체 PASS.

- [ ] **Step 4: 최종 diff 검사**

```bash
git diff 4b31412 --stat
```

Expected: 변경된 파일이 소스 11개 + 새 테스트 1개 + `CLAUDE.md` 뿐이다. **선행 조건 1·2 로 인한 변경은 별도 커밋이므로 여기 섞이면 안 된다.** 섞였다면 선행 조건을 건너뛰고 시작한 것이다.

- [ ] **Step 5: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: 주석 규칙을 프로젝트 규칙으로 남긴다"
```

---

## 자기 검토 결과

스펙 대비 확인한 것을 남긴다.

| 스펙 항목 | 담당 |
|---|---|
| §3 응용 축 11개 모듈 | Task 1 (5개), Task 2 (6개) |
| §4 밀도 보강 6곳 | Task 3 (5곳) + Task 2 Step 8 (`__init__.py`) |
| §5 `CLAUDE.md` 규칙 | Task 4 |
| §6 전체 테스트 통과 | 각 Task 마지막 |
| §6 diff 에 주석 외의 줄 없음 | Task 4 Step 4 |
| §6 스펙 §N 대조 | Task 3 Step 6 |
| §6 11개 모듈 전부 확인 | Task 2 Step 1 의 테스트가 자동화 |
| §7 범위 밖 (README, 리팩터링, 마커) | Global Constraints |

**스펙에 없던 추가 하나:** `tests/test_comment_conventions.py`. 스펙 §6 의 "11개 모듈 전부에 `## 응용할 때` 가 있는지 확인한다" 를 사람 눈에서 테스트로 옮긴 것이다. 주석 작업에는 TDD 를 걸 대상이 이것뿐이고, 이 파일이 없으면 규칙이 다음 모듈에서 곧바로 잊힌다.
