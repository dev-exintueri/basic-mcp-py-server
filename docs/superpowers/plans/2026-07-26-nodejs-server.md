# Node.js 서버 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파이썬 MCP 테스트 서버와 밖에서 구별되지 않는 Node.js 서버를 만들고, 공유 적합성 스위트가 그 동일함을 강제하게 한다.

**Architecture:** `plugins/mcp-test/server-node/` 에 TypeScript + express 5 서버를 새로 만든다. `plugins/mcp-test/conformance/` 의 pytest 스위트가 `--target=python|node` 로 두 서버를 같은 단언으로 검증한다. 슬라이스 셋(MCP 핵심 → 관리 API → 로깅)을 각각 "스위트 작성 → 파이썬 통과 → 노드 구현 → 노드 통과" 로 돈다.

**Tech Stack:** TypeScript 5.9, express 5.2.1, `@modelcontextprotocol/sdk` 1.29.0, zod 3.25, vitest 4, pytest + httpx + mcp 클라이언트

**설계 문서:** `docs/superpowers/specs/2026-07-26-nodejs-server-design.md`

---

## Global Constraints

이 절의 모든 항목은 **모든 태스크의 요구사항에 암묵적으로 포함된다.**

- **런타임 버전:** Node >= 20. SDK 는 >=18 을 요구하지만 20 으로 올려 잡는다.
- **의존성 고정:** `@modelcontextprotocol/sdk` 는 `1.29.0` 정확히 고정한다. 아래 모든 API 주장은 이 버전을 실제로 설치해 검증한 것이다.
- **`createMcpExpressApp()` 을 쓰지 않는다.** 이 헬퍼는 host 가 `127.0.0.1` 일 때 DNS 리바인딩 보호(Host 헤더 검증)를 자동으로 건다. 파이썬 서버에 없는 동작이다. 순수 `express()` 를 쓴다.
- **시계 주입.** 파이썬 쪽 전역 제약을 따른다. `Date.now()` / `new Date()` 를 모듈 안에서 직접 부르지 않는다. `clock: () => Date` 를 인자로 받는다. 진입점(`main.ts`)만 실제 시계를 만든다.
- **주석은 한국어.** 모든 `src/*.ts` 파일 머리에 JSDoc 블록 주석을 두고 그 안에 `## 응용할 때` 절을 둔다. 코드 식별자는 원형 그대로 둔다. **줄 번호로 코드를 가리키지 않는다** — 파일명과 심볼명으로 가리킨다.
- **로그 줄 형식:** `<스탬프> <레벨5칸> <카테고리8칸> <메시지>`. 아래 값은 파이썬 서버를 실제로 띄워 받은 것이다.

  ```
  2026-07-26T01:35:31Z INFO  app      서버 기동 MCP=127.0.0.1:18765 관리=127.0.0.1:18766
  2026-07-26T01:35:36Z WARN  http     POST /mcp 401 dur_ms=0 reason=blank-token
  2026-07-26T01:35:36Z INFO  registry connected instance=abc123def456 subject=al…(sha256:2bd806c9) label=unnamed
  ```

- **스탬프:** `clock().toISOString().replace(/\.\d{3}Z$/, 'Z')` — 밀리초를 버린다. 검증됨.
- **마스킹:** 앞 두 글자 + `…`(U+2026) + `(sha256:앞8자리)`. `alice` → `al…(sha256:2bd806c9)`. 파이썬 출력과 바이트 일치 검증됨.
- **레벨 이름:** `WARNING`→`WARN`, `CRITICAL`→`ERROR`. 우리 로거는 `INFO` / `WARN` / `ERROR` 만 쓴다.
- **모르는 카테고리를 허용한다.** 스위트는 우리 카테고리(`app` `http` `registry` `call`)로 **필터링**해서 찾고, 다른 카테고리가 섞여 있다고 실패하지 않는다. 파이썬 쪽에는 `error`(uvicorn), `streamable_http_manager`, `transport_security` 가 섞인다.

### 검증된 SDK 사실

아래는 SDK 1.29.0 을 설치하고 실제로 서버를 띄워 파이썬 MCP 클라이언트로 두드려 확인한 것이다. **추론이 아니다.**

| 사실 | 내용 |
|---|---|
| import | `@modelcontextprotocol/sdk/server/mcp.js` → `McpServer`; `/server/streamableHttp.js` → `StreamableHTTPServerTransport`; `/types.js` → `isInitializeRequest` |
| 도구 등록 | `registerTool(name, { description, inputSchema? }, cb)` |
| **콜백 인자 규약** | `inputSchema` 가 **있으면** `(args, extra)`, **없으면** `(extra)`. `mcp.js` 의 `executeToolHandler` 가 갈린다 |
| 헤더 접근 | `extra.requestInfo.headers` — **소문자 키**. `Record<string, string \| string[] \| undefined>` |
| stateful | `new StreamableHTTPServerTransport({ sessionIdGenerator: () => randomUUID(), onsessioninitialized: (id) => {...} })` |
| 요청 처리 | `transport.handleRequest(req, res, req.body)` |
| 반환 콘텐츠 | `{ content: [{ type: 'text' as const, text }] }` — TS strict 에서 `as const` 가 필요하다 |
| tsconfig | `target: ES2022`, `module: NodeNext`, `moduleResolution: NodeNext`, `strict: true` 로 빌드 통과 검증됨 |

**가장 위험한 함정:** `ping` `whoami` `sessions` 는 인자가 없으므로 콜백이 `(extra) => ...` 다. 습관대로 `(_args, extra) => ...` 라고 쓰면 `extra` 가 첫 인자에 들어가 두 번째는 `undefined` 가 되고, **`whoami` 가 연결 ID 를 조용히 놓친다.** 오류는 나지 않는다. 실제로 이 함정에 빠졌다가 발견했다.

---

## 파일 구조

### 새로 만드는 것

| 파일 | 책임 |
|---|---|
| `server-node/package.json` | 의존성, `build`/`test` 스크립트 |
| `server-node/tsconfig.json` | 컴파일 설정 |
| `server-node/src/main.ts` | CLI 파싱, 로깅 준비, `serve()` 호출 |
| `server-node/src/app.ts` | 두 리스너 조립과 기동, 포트 선점 확인, 노출 경고 |
| `server-node/src/auth.ts` | `readIdentity`, `maskSecret`, 인증·차단 미들웨어 |
| `server-node/src/access.ts` | 접근 로그 미들웨어 |
| `server-node/src/registry.ts` | 세션 레지스트리와 `sessionView` |
| `server-node/src/mcpServer.ts` | `McpServer` 조립, 도구 4개, 호출 로그 |
| `server-node/src/mcpRoute.ts` | 세션별 transport Map 라우팅 |
| `server-node/src/admin.ts` | 관리 앱 라우트와 HTML |
| `server-node/src/logging.ts` | 포매터, 레벨, 일별 파일 핸들러, 카테고리 로거 |
| `server-node/src/logPaths.ts` | 경로 우선순위 해석, `purgeLogs`, `tailLines` |
| `server-node/src/logStream.ts` | SSE 브로드캐스터 |
| `conformance/pyproject.toml` | 스위트 의존성 |
| `conformance/conftest.py` | `--target` 플래그, 서버 기동 픽스처, 빌드 강제 |
| `conformance/test_mcp.py` | 슬라이스 1 |
| `conformance/test_admin.py` | 슬라이스 2 |
| `conformance/test_logging.py` | 슬라이스 3 |

### 고치는 것

| 파일 | 변경 |
|---|---|
| `server/src/mcp_test_server/admin.py` | `/api/status` 에 `runtime` 필드 |
| `server/tests/test_admin.py` | 그 필드 검증 |
| `commands/server-start.md` | 런타임 인자 |
| `hooks/check-server.sh` | 안내 문구 |
| `README.md`, `CLAUDE.md` | 문서 |

---

## Task 1: 적합성 하네스와 파이썬 타깃

스위트의 뼈대를 세우고 파이썬 서버를 상대로 돌아가게 만든다. 노드 타깃은 다음 태스크에서 켠다.

**Files:**
- Create: `plugins/mcp-test/conformance/pyproject.toml`
- Create: `plugins/mcp-test/conformance/conftest.py`
- Create: `plugins/mcp-test/conformance/test_mcp.py`

**Interfaces:**
- Produces: `server` 픽스처 — `ServerHandle` 를 내준다. 속성은 `mcp_url: str`, `admin_url: str`, `log_dir: Path`, `port: int`, `admin_port: int`, `runtime: str`. 이후 모든 테스트가 이 픽스처만 쓴다.
- Produces: `HEADERS: dict[str, str]` — 표준 클라이언트 헤더.

- [ ] **Step 1: `pyproject.toml` 을 만든다**

```toml
[project]
name = "mcp-test-conformance"
version = "0.1.0"
description = "파이썬 서버와 노드 서버가 같은 계약을 지키는지 검증한다"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.28,<2",
    "httpx>=0.27",
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-timeout>=2.3",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
timeout = 60
```

`testpaths` 를 두지 않는다. 이 디렉토리의 테스트가 전부다.

- [ ] **Step 2: `conftest.py` 를 만든다**

```python
"""두 런타임을 같은 단언으로 검증하기 위한 기동 하네스.

--target 으로 무엇을 띄울지 고른다. 단언은 테스트 파일에 있고, 이 파일은
"어떻게 띄우는가" 만 안다. 그 차이가 두 런타임 사이의 유일한 차이여야 한다.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "mcp-test"
PY_SERVER = PLUGIN_ROOT / "server"
NODE_SERVER = PLUGIN_ROOT / "server-node"

HEADERS = {
    "Authorization": "Bearer alice",
    "X-Client-Instance": "abc123def456",
    "X-Client-Project": "/tmp/proj",
    "X-Client-Label": "left",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--target",
        action="store",
        default="python",
        choices=("python", "node"),
        help="검증할 서버 런타임",
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class ServerHandle:
    runtime: str
    port: int
    admin_port: int
    log_dir: Path
    mcp_url: str
    admin_url: str
    proc: subprocess.Popen
    stdout_path: Path

    def output(self) -> str:
        try:
            return self.stdout_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def log_text(self) -> str:
        """서버가 남긴 로그 파일 전체. 없으면 빈 문자열."""
        files = sorted(self.log_dir.glob("mcp-test-server.*.log"))
        return "".join(f.read_text(encoding="utf-8", errors="replace") for f in files)


def base_command(runtime: str) -> list[str]:
    """서버를 띄우는 명령. 인자는 붙이지 않는다.

    두 런타임의 차이는 이 함수 하나에 갇혀 있어야 한다. 인자를 여기서 함께
    조립하면 인자를 바꿔 띄우고 싶은 테스트가 슬라이싱으로 떼어내게 되고,
    그것은 명령이 길어질 때 조용히 깨진다.
    """
    if runtime == "python":
        return ["uv", "run", "--directory", str(PY_SERVER), "mcp-test-server"]
    return ["node", str(NODE_SERVER / "dist" / "main.js")]


def _ensure_built(runtime: str) -> None:
    """노드 타깃은 빌드가 최신이어야 한다.

    dist/ 가 낡았거나 없으면 어제 코드를 검증하고 초록을 보고한다. skip 하지
    않는 것도 중요하다 — skip 은 요약 줄에서 "덮었다" 로 읽힌다.
    """
    if runtime != "node":
        return
    if not (NODE_SERVER / "node_modules").is_dir():
        raise RuntimeError(
            f"{NODE_SERVER}/node_modules 가 없다. npm install 을 먼저 돌려라. "
            "이 상황을 skip 으로 넘기지 않는다"
        )
    result = subprocess.run(
        ["npm", "run", "build"], cwd=NODE_SERVER, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"노드 빌드 실패:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="function")
def server(request: pytest.FixtureRequest, tmp_path: Path):
    runtime = request.config.getoption("--target")
    _ensure_built(runtime)

    port, admin_port = free_port(), free_port()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    stdout_path = tmp_path / "server.out"

    args = [
        *base_command(runtime),
        "--port", str(port),
        "--admin-port", str(admin_port),
        "--log-dir", str(log_dir),
    ]
    with stdout_path.open("wb") as sink:
        proc = subprocess.Popen(args, stdout=sink, stderr=subprocess.STDOUT)

    handle = ServerHandle(
        runtime=runtime,
        port=port,
        admin_port=admin_port,
        log_dir=log_dir,
        mcp_url=f"http://127.0.0.1:{port}/mcp",
        admin_url=f"http://127.0.0.1:{admin_port}",
        proc=proc,
        stdout_path=stdout_path,
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"서버가 기동 중 죽었다:\n{handle.output()}")
        try:
            # 인증 없는 POST 에 401 이 오면 살아 있는 것이다. 401 은 서버가
            # 떴다는 것과 인증이 실제로 걸려 있다는 것을 함께 증명한다.
            if httpx.post(handle.mcp_url, timeout=1).status_code == 401:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"서버가 30초 안에 뜨지 않았다:\n{handle.output()}")

    try:
        yield handle
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
```

- [ ] **Step 3: 첫 계약 테스트를 쓴다**

`test_mcp.py`:

```python
"""슬라이스 1 — MCP 핵심의 계약."""

from __future__ import annotations

import httpx

from conftest import HEADERS


def test_unauthenticated_post_is_rejected_with_401(server) -> None:
    response = httpx.post(server.mcp_url, timeout=5)
    assert response.status_code == 401
    # 문구는 계약하지 않는다. 키의 존재만 본다.
    assert "error" in response.json()


def test_blank_bearer_token_is_rejected(server) -> None:
    response = httpx.post(
        server.mcp_url, headers={"Authorization": "Bearer   "}, timeout=5
    )
    assert response.status_code == 401
```

- [ ] **Step 4: 파이썬 타깃으로 돌려서 통과를 본다**

Run:
```bash
cd /Users/gdsr/workspace/dev-exintueri/basic-mcp-py-server
uv run --directory plugins/mcp-test/conformance pytest -v --target=python
```
Expected: 2 passed

- [ ] **Step 5: 노드 타깃이 조용히 통과하지 않는지 본다**

Run:
```bash
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: **ERROR** — `node_modules 가 없다`. skip 이나 pass 가 나오면 하네스가 틀린 것이다.

- [ ] **Step 6: 커밋**

```bash
git add plugins/mcp-test/conformance
git commit -m "test(conformance): 두 런타임을 같은 단언으로 모는 하네스"
```

---

## Task 2: 노드 스캐폴딩과 인증

노드 서버가 뜨고, 인증 미들웨어가 붙고, 접근 로그가 401 을 남긴다. Task 1 의 두 테스트를 노드로도 통과시킨다.

**Files:**
- Create: `plugins/mcp-test/server-node/package.json`, `tsconfig.json`, `.gitignore`
- Create: `plugins/mcp-test/server-node/src/auth.ts`, `access.ts`, `logging.ts`, `app.ts`, `main.ts`
- Create: `plugins/mcp-test/server-node/tests/auth.test.ts`

**Interfaces:**
- Produces: `auth.ts` → `interface Identity { subject, instanceId, project, label, mcpSessionId }`, `readIdentity(headers: IncomingHttpHeaders): Identity | null`, `maskSecret(value: string): string`, `AUTH_KEY` 심볼로 `req` 에 붙이는 신원.
- Produces: `logging.ts` → `type Clock = () => Date`, `formatLine(clock, level, category, message): string`, `getLogger(category): Logger` where `Logger = { info(msg), warn(msg), error(msg) }`, `configureLogging(opts)`.
- Produces: `access.ts` → `accessLog(): RequestHandler`.
- Produces: `app.ts` → `serve(options): Promise<void>`.

- [ ] **Step 1: `package.json` 을 만든다**

```json
{
  "name": "mcp-test-server-node",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "여러 Claude Code 세션이 하나의 노드 프로세스에 붙는 MCP 테스트 서버",
  "engines": { "node": ">=20" },
  "scripts": {
    "build": "tsc",
    "test": "vitest run"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "1.29.0",
    "express": "^5.2.1",
    "zod": "^3.25.0"
  },
  "devDependencies": {
    "@types/express": "^5.0.0",
    "@types/node": "^22.0.0",
    "typescript": "^5.9.0",
    "vitest": "^4.0.0"
  }
}
```

- [ ] **Step 2: `tsconfig.json` 과 `.gitignore` 를 만든다**

`tsconfig.json` — 이 설정으로 빌드가 통과하는 것을 검증했다:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "declaration": false,
    "sourceMap": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts"]
}
```

`.gitignore`:

```
node_modules/
dist/
```

- [ ] **Step 3: `npm install` 로 의존성을 받는다**

Run:
```bash
cd plugins/mcp-test/server-node && npm install
```
Expected: 종료 코드 0, `node_modules/` 생성

- [ ] **Step 4: `logging.ts` 의 실패 테스트를 쓴다**

`tests/logging.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { formatLine } from '../src/logging.js';

const fixed = () => new Date('2026-07-26T01:35:36.789Z');

describe('formatLine', () => {
  it('밀리초를 버리고 레벨 5칸 카테고리 8칸으로 맞춘다', () => {
    // 파이썬 서버가 실제로 낸 줄과 바이트가 같아야 한다.
    expect(formatLine(fixed, 'WARN', 'http', 'POST /mcp 401 dur_ms=0 reason=blank-token'))
      .toBe('2026-07-26T01:35:36Z WARN  http     POST /mcp 401 dur_ms=0 reason=blank-token');
  });

  it('8칸을 넘는 카테고리는 자르지 않는다', () => {
    // 파이썬 쪽 streamable_http_manager 가 그렇다. 잘라내면 정보가 사라진다.
    expect(formatLine(fixed, 'INFO', 'verylongcategory', 'x'))
      .toBe('2026-07-26T01:35:36Z INFO  verylongcategory x');
  });
});
```

- [ ] **Step 5: 실패를 확인한다**

Run: `npm test`
Expected: FAIL — `../src/logging.js` 를 찾을 수 없다

- [ ] **Step 6: `logging.ts` 를 쓴다**

```ts
/**
 * 로그 줄의 형식과 목적지.
 *
 * 파이썬 쪽은 표준 logging 의 루트 로거에 핸들러를 붙이지만, 노드에는
 * 그런 전역 로깅이 없다. 대신 카테고리별 로거를 만들어 같은 형식의 줄을
 * 같은 목적지로 보낸다. 목적지는 프로세스 전역 상태이므로 configureLogging()
 * 이 한 번만 정한다.
 *
 * 스탬프에 밀리초를 남기지 않는다. toISOString() 은 붙이므로 잘라낸다 —
 * 파이썬의 strftime("%Y-%m-%dT%H:%M:%SZ") 와 같은 줄을 만들기 위해서다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** formatLine() 의 줄 형식과 레벨 이름.
 *
 * **함께 바꿔야 하는 것.** 줄 형식을 바꾸면 관리 화면의 로그 패널과
 * logPaths 의 tailLines() 백필이 그 형식을 그대로 보여주므로 함께 본다.
 * 그리고 conformance 스위트가 이 형식을 단언한다.
 *
 * **깨면 안 되는 것.** 카테고리가 8칸을 넘어도 자르지 않는다. 자르면
 * 어느 로거가 냈는지 알 수 없어진다.
 */

export type Clock = () => Date;
export type Level = 'INFO' | 'WARN' | 'ERROR';

export function stamp(clock: Clock): string {
  return clock().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function formatLine(
  clock: Clock,
  level: Level,
  category: string,
  message: string,
): string {
  return `${stamp(clock)} ${level.padEnd(5)} ${category.padEnd(8)} ${message}`;
}

export interface Logger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

type Sink = (line: string) => void;

let sinks: Sink[] = [];
let currentClock: Clock = () => new Date();

export function configureLogging(options: { clock: Clock; sinks: Sink[] }): void {
  currentClock = options.clock;
  sinks = options.sinks;
}

export function resetLogging(): void {
  sinks = [];
  currentClock = () => new Date();
}

export function getLogger(category: string): Logger {
  const emit = (level: Level, message: string): void => {
    const line = formatLine(currentClock, level, category, message);
    for (const sink of sinks) {
      try {
        sink(line);
      } catch {
        // 로깅이 애플리케이션을 죽이면 안 된다. 한 목적지가 실패해도
        // 나머지 목적지에는 남긴다.
      }
    }
  };
  return {
    info: (m) => emit('INFO', m),
    warn: (m) => emit('WARN', m),
    error: (m) => emit('ERROR', m),
  };
}
```

- [ ] **Step 7: 테스트가 통과하는지 본다**

Run: `npm test`
Expected: 2 passed

- [ ] **Step 8: `auth.ts` 의 실패 테스트를 쓴다**

`tests/auth.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { maskSecret, readIdentity } from '../src/auth.js';

describe('maskSecret', () => {
  it('파이썬과 같은 문자열을 만든다', () => {
    // 파이썬 서버가 실제로 남긴 값이다.
    expect(maskSecret('alice')).toBe('al…(sha256:2bd806c9)');
  });

  it('빈 값은 (empty)', () => {
    expect(maskSecret('')).toBe('(empty)');
  });
});

describe('readIdentity', () => {
  it('Bearer 뒤가 비면 통과시키지 않는다', () => {
    expect(readIdentity({ authorization: 'Bearer    ' })).toBeNull();
  });

  it('Authorization 이 없으면 통과시키지 않는다', () => {
    expect(readIdentity({})).toBeNull();
  });

  it('헤더가 없으면 파이썬과 같은 기본값을 쓴다', () => {
    const identity = readIdentity({ authorization: 'Bearer alice' });
    expect(identity).toEqual({
      subject: 'alice',
      instanceId: 'unknown',
      project: '',
      label: 'unnamed',
      mcpSessionId: null,
    });
  });
});
```

- [ ] **Step 9: 실패를 확인한다**

Run: `npm test`
Expected: FAIL — `../src/auth.js` 를 찾을 수 없다

- [ ] **Step 10: `auth.ts` 를 쓴다**

```ts
/**
 * 요청 헤더에서 신원을 읽고, 인증하고, 차단한다.
 *
 * X-Client-Instance 는 클라이언트가 스스로 주장하는 값이고 검증하지 않는다.
 * sessions 도구가 모든 연결 ID 를 모든 세션에 공개하므로, 비어 있지 않은
 * 토큰만 있으면 누구나 남의 ID 로 요청을 보내 그 세션의 값을 덮어쓸 수 있다.
 * 피해는 제한적이고 이 설계에 내재한 성질이므로 막지 않는다. 사실로 남겨 둔다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** readIdentity() 의 통과 조건이 이 서버의 인증 전부다.
 * 진짜 인증을 넣는다면 여기다 — Identity 를 돌려주거나 null 을 돌려주기만
 * 하면 나머지는 그대로 동작한다.
 *
 * **함께 바꿔야 하는 것.** 헤더 이름을 바꾸면 플러그인 쪽 .mcp.json 의
 * headers 와 scripts/connection-id.sh 가 따라온다. Identity 에 필드를
 * 더하면 registry 의 touch() 도 따라온다.
 *
 * **깨면 안 되는 것.** 인증 미들웨어는 접근 로그 미들웨어보다 **나중에**
 * 등록해야 한다. express 에서 등록 순서가 곧 바깥/안쪽이고, 먼저 등록하면
 * 401/403 으로 거부된 요청이 접근 로그에 남지 않는다 — 이 서버에서 가장
 * 보고 싶은 줄이 그것이다.
 */

import { createHash } from 'node:crypto';
import type { IncomingHttpHeaders } from 'node:http';
import type { NextFunction, Request, RequestHandler, Response } from 'express';

import { getLogger } from './logging.js';
import type { Registry } from './registry.js';
import type { Clock } from './logging.js';

const registryLogger = getLogger('registry');

export const UNKNOWN_INSTANCE = 'unknown';
const BEARER_PREFIX = 'bearer ';

export interface Identity {
  subject: string;
  instanceId: string;
  project: string;
  label: string;
  mcpSessionId: string | null;
}

/** access.ts 가 읽는 요청 부착 정보. 스키마는 이 모듈이 정의한다. */
export interface AuthInfo {
  instance: string | null;
  subject: string | null;
  reason: string | null;
}

declare module 'express-serve-static-core' {
  interface Request {
    mcpTestAuth?: AuthInfo;
  }
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function readIdentity(headers: IncomingHttpHeaders): Identity | null {
  const authorization = first(headers['authorization']);
  if (authorization === undefined) return null;
  if (!authorization.toLowerCase().startsWith(BEARER_PREFIX)) return null;

  const subject = authorization.slice(BEARER_PREFIX.length).trim();
  if (!subject) return null;

  return {
    subject,
    instanceId: first(headers['x-client-instance']) || UNKNOWN_INSTANCE,
    project: first(headers['x-client-project']) || '',
    label: first(headers['x-client-label']) || 'unnamed',
    mcpSessionId: first(headers['mcp-session-id']) ?? null,
  };
}

export function maskSecret(value: string): string {
  if (!value) return '(empty)';
  const digest = createHash('sha256').update(value, 'utf8').digest('hex').slice(0, 8);
  return `${value.slice(0, 2)}…(sha256:${digest})`;
}

export function authMiddleware(registry: Registry, clock: Clock): RequestHandler {
  return (req: Request, res: Response, next: NextFunction): void => {
    const identity = readIdentity(req.headers);
    if (identity === null) {
      req.mcpTestAuth = { instance: null, subject: null, reason: 'blank-token' };
      res
        .status(401)
        .set('WWW-Authenticate', 'Bearer')
        .json({ error: 'Authorization 헤더에 비어 있지 않은 Bearer 토큰이 필요하다' });
      return;
    }

    if (registry.isBlocked(identity.instanceId)) {
      req.mcpTestAuth = {
        instance: identity.instanceId,
        subject: identity.subject,
        reason: 'blocked',
      };
      res
        .status(403)
        .json({ error: `연결 ${identity.instanceId} 이(가) 관리 화면에서 차단되었다` });
      return;
    }

    req.mcpTestAuth = {
      instance: identity.instanceId,
      subject: identity.subject,
      reason: null,
    };

    // DELETE 는 연결을 끊는 요청이지 새로 맺는 요청이 아니다. 아래 "처음 보는
    // 연결" 로그보다 먼저 갈라져야, 레지스트리가 모르는 인스턴스로 DELETE 가
    // 와도 connected 가 찍히지 않는다.
    if (req.method === 'DELETE') {
      registry.remove(identity.instanceId);
      next();
      return;
    }

    if (registry.get(identity.instanceId) === undefined) {
      // touch 하면 레코드가 생겨 버리므로 그 전에 본다.
      registryLogger.info(
        `connected instance=${identity.instanceId} ` +
          `subject=${maskSecret(identity.subject)} label=${identity.label}`,
      );
    }

    registry.touch({ ...identity, now: clock() });
    next();
  };
}
```

- [ ] **Step 11: `registry.ts` 를 쓴다**

`auth.ts` 가 이것을 import 하므로 먼저 있어야 한다.

```ts
/**
 * 세션 레지스트리. 이 프로세스의 유일한 상태 보유자다.
 *
 * 노드는 단일 스레드이고 아래 메서드는 전부 동기 함수이므로 락이 없다.
 * 파이썬 쪽과 같은 전제다 — 레코드를 읽은 뒤 고치기까지 사이에서 await
 * 하지 않는다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** SessionRecord 의 필드와 sessionView() 의 출력이
 * 이 서버가 세션에 대해 무엇을 아는지 정한다.
 *
 * **함께 바꿔야 하는 것.** 필드를 늘리면 두 곳이 따라온다 — 값을 어디서
 * 얻는가(auth 의 Identity 와 touch() 호출), 화면에 어떻게 보이는가
 * (admin 의 행 템플릿과 열 제목). 그리고 conformance 스위트가
 * sessionView 의 키 집합을 단언한다.
 *
 * **깨면 안 되는 것.** 갱신 도중 await 하는 비동기 메서드를 더하지 않는다.
 */

export interface SessionRecord {
  instanceId: string;
  subject: string;
  project: string;
  label: string;
  mcpSessionId: string | null;
  connectedAt: Date;
  lastSeen: Date;
  callCount: number;
  blocked: boolean;
}

export interface TouchInput {
  instanceId: string;
  subject: string;
  project: string;
  label: string;
  mcpSessionId: string | null;
  now: Date;
}

export class Registry {
  private records = new Map<string, SessionRecord>();

  constructor(
    public staleAfter = 300.0,
    public purgeAfter = 86400.0,
  ) {}

  touch(input: TouchInput): SessionRecord {
    const existing = this.records.get(input.instanceId);
    if (existing === undefined) {
      const record: SessionRecord = {
        instanceId: input.instanceId,
        subject: input.subject,
        project: input.project,
        label: input.label,
        mcpSessionId: input.mcpSessionId,
        connectedAt: input.now,
        lastSeen: input.now,
        callCount: 1,
        blocked: false,
      };
      this.records.set(input.instanceId, record);
      return record;
    }
    existing.lastSeen = input.now;
    existing.callCount += 1;
    existing.subject = input.subject;
    existing.project = input.project;
    existing.label = input.label;
    if (input.mcpSessionId !== null) existing.mcpSessionId = input.mcpSessionId;
    return existing;
  }

  get(instanceId: string): SessionRecord | undefined {
    return this.records.get(instanceId);
  }

  all(): SessionRecord[] {
    return [...this.records.values()];
  }

  remove(instanceId: string): boolean {
    return this.records.delete(instanceId);
  }

  block(instanceId: string): boolean {
    const record = this.records.get(instanceId);
    if (record === undefined) return false;
    record.blocked = true;
    return true;
  }

  unblock(instanceId: string): boolean {
    const record = this.records.get(instanceId);
    if (record === undefined) return false;
    record.blocked = false;
    return true;
  }

  isBlocked(instanceId: string): boolean {
    return this.records.get(instanceId)?.blocked ?? false;
  }

  isStale(record: SessionRecord, now: Date): boolean {
    return (now.getTime() - record.lastSeen.getTime()) / 1000 > this.staleAfter;
  }

  purge(now: Date): number {
    const doomed = this.all().filter(
      (r) => (now.getTime() - r.lastSeen.getTime()) / 1000 > this.purgeAfter,
    );
    for (const record of doomed) this.records.delete(record.instanceId);
    return doomed.length;
  }
}

/**
 * 세션 레코드를 JSON 으로 옮길 수 있는 형태로 바꾼다.
 *
 * MCP 도구와 관리 앱이 같은 표현을 쓰도록 여기 한 곳에만 둔다. 키 이름은
 * 파이썬 쪽 session_view() 와 같은 snake_case 다 — 이것이 계약이다.
 */
export function sessionView(
  record: SessionRecord,
  registry: Registry,
  now: Date,
): Record<string, unknown> {
  return {
    instance_id: record.instanceId,
    subject: record.subject,
    project: record.project,
    label: record.label,
    mcp_session_id: record.mcpSessionId,
    connected_at: record.connectedAt.toISOString(),
    last_seen: record.lastSeen.toISOString(),
    call_count: record.callCount,
    blocked: record.blocked,
    stale: registry.isStale(record, now),
  };
}
```

- [ ] **Step 12: `access.ts` 를 쓴다**

```ts
/**
 * 접근 로그 미들웨어. 요청 하나당 줄 하나, 거부된 요청도 포함한다.
 *
 * ## 응용할 때
 *
 * 포크해도 대개 그대로 둔다. 고친다면 어떤 필드를 남기는지 정도다.
 *
 * **깨면 안 되는 것.**
 *
 * - 이 미들웨어를 authMiddleware 보다 **먼저** 등록한다. express 에서
 *   등록 순서가 곧 바깥/안쪽이다. 뒤집으면 401/403 으로 거부된 요청이
 *   로그에 남지 않는다.
 * - 로그는 응답이 **시작**될 때 남긴다. res.on('finish') 로 옮기면
 *   /api/logs/stream 같은 SSE 연결은 브라우저 탭이 닫힐 때까지 아무 줄도
 *   남기지 않는다. 그래서 writeHead 를 감싼다. 그 대신 SSE 연결은 열리는
 *   순간 dur_ms 가 0에 가까운 줄 하나를 남기고 갱신되지 않는다. 의도한
 *   동작이다.
 * - 캐리지 리턴과 줄바꿈 이스케이프는 조립이 끝난 한 줄에 한 번 건다.
 *   필드마다 거는 방식으로 바꾸면 새 필드가 생길 때 조용히 샌다.
 */

import type { NextFunction, Request, RequestHandler, Response } from 'express';

import { maskSecret } from './auth.js';
import { getLogger } from './logging.js';

const logger = getLogger('http');

export function accessLog(): RequestHandler {
  return (req: Request, res: Response, next: NextFunction): void => {
    const started = process.hrtime.bigint();
    let logged = false;

    const write = (status: number): void => {
      if (logged) return;
      logged = true;
      const durationMs = Number(process.hrtime.bigint() - started) / 1e6;

      const parts = [req.method, req.originalUrl, String(status), `dur_ms=${durationMs.toFixed(0)}`];
      const info = req.mcpTestAuth;
      if (info?.instance) parts.push(`instance=${info.instance}`);
      if (info?.subject) parts.push(`subject=${maskSecret(info.subject)}`);
      if (info?.reason) parts.push(`reason=${info.reason}`);

      // 줄바꿈을 이스케이프한 뒤에 넘긴다. 경로와 연결 ID 는 클라이언트가
      // 정하는 값이고 마스킹도 걸리지 않는다. 날것으로 두면 요청 하나로
      // 진짜와 구별되지 않는 로그 줄을 만들어 넣을 수 있고(위조), 캐리지
      // 리턴은 그보다 나쁘다 — SSE 프레이밍은 줄바꿈만 나누므로 캐리지
      // 리턴이 든 줄은 관리 화면에서 통째로 사라진다(은폐). 토큰 없이도
      // 되는 일이라 401 로 거부된 요청에도 해당한다.
      const line = parts.join(' ').replace(/\r/g, '\\r').replace(/\n/g, '\\n');
      if (status >= 400) logger.warn(line);
      else logger.info(line);
    };

    const originalWriteHead = res.writeHead.bind(res);
    // 첫 바이트에서 남기기 위해 writeHead 를 감싼다. 자세한 이유는 위
    // 모듈 주석에 있다.
    res.writeHead = function patched(this: Response, ...args: unknown[]) {
      write(res.statusCode);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (originalWriteHead as any)(...args);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;

    // 응답을 한 번도 시작하지 못하고 끊긴 경우다. 상태는 없지만 요청이
    // 있었다는 사실은 남겨야 한다.
    res.on('close', () => write(0));

    next();
  };
}
```

- [ ] **Step 13: `app.ts` 와 `main.ts` 를 쓴다**

`app.ts`:

```ts
/**
 * 두 리스너를 조립하고 한 프로세스에서 함께 기동한다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** DEFAULTS 의 포트와 유휴 기준, 그리고 buildMcpApp() 이
 * 무엇을 무엇으로 감싸는지. 미들웨어를 더한다면 거기다.
 *
 * **깨면 안 되는 것.**
 *
 * - accessLog() 를 authMiddleware() 보다 **먼저** 등록한다. 순서가 곧
 *   바깥/안쪽이다.
 * - 관리 리스너의 주소는 ADMIN_HOST 고정이다. 인증이 없는 리스너이므로
 *   바꿀 수 있는 통로를 만들지 않는다.
 * - createMcpExpressApp() 을 쓰지 않는다. 그 헬퍼는 Host 헤더 검증을
 *   자동으로 걸어 파이썬 서버와 동작이 갈린다.
 */

import express from 'express';
import type { Express } from 'express';
import { createServer, type Server } from 'node:http';

import { accessLog } from './access.js';
import { authMiddleware } from './auth.js';
import { getLogger, type Clock } from './logging.js';
import { Registry } from './registry.js';

const logger = getLogger('app');

// 관리 리스너는 루프백에 고정한다. 인증이 없는 리스너이므로 이 값을 바꿀 수
// 있는 통로를 만들지 않는다.
export const ADMIN_HOST = '127.0.0.1';

export const DEFAULTS = {
  host: '127.0.0.1',
  port: 8765,
  adminPort: 8766,
  staleAfter: 300.0,
};

const WILDCARD_HOSTS = new Set(['0.0.0.0', '::']);

export function isLoopback(host: string): boolean {
  return host === '127.0.0.1' || host === '::1' || host.toLowerCase() === 'localhost';
}

/** 바인딩 주소를 클라이언트가 실제로 접속할 수 있는 주소로 바꾼다. */
export function endpointHost(host: string): string {
  return WILDCARD_HOSTS.has(host) ? '127.0.0.1' : host;
}

/**
 * 루프백 밖에 노출될 때 보여줄 경고문. 안전하면 null.
 *
 * serve() 안에 인라인으로 두면 경고 여부를 판단하는 규칙을 테스트가 확인할
 * 수 없다. 아무것도 출력하지 않는 순수 함수로 떼어 둔다.
 */
export function exposureWarning(host: string): string | null {
  if (isLoopback(host)) return null;
  return (
    `경고: ${host} 는 루프백 주소가 아니다. 이 서버의 인증은 비어 있지 않은 ` +
    'Bearer 토큰이면 무엇이든 통과시키므로, 이 포트에 닿을 수 있는 사람은 ' +
    '누구나 연결된 모든 세션의 프로젝트 경로와 토큰을 읽고 세션을 지울 수 ' +
    '있다. 신뢰할 수 없는 망에서는 쓰지 마라.'
  );
}

export interface ServeOptions {
  host: string;
  port: number;
  adminPort: number;
  staleAfter: number;
  clock: Clock;
}

export function buildMcpApp(registry: Registry, clock: Clock): Express {
  const app = express();
  // 순서가 계약이다. 접근 로그가 바깥, 인증이 안쪽.
  app.use(accessLog());
  app.use(authMiddleware(registry, clock));
  return app;
}

export async function serve(options: ServeOptions): Promise<{ close: () => Promise<void> }> {
  const warning = exposureWarning(options.host);
  if (warning !== null) {
    process.stderr.write(warning + '\n');
    logger.warn(warning);
  }

  const registry = new Registry(options.staleAfter);
  const mcpApp = buildMcpApp(registry, options.clock);

  const mcpServer = createServer(mcpApp);
  await listen(mcpServer, options.port, options.host);

  process.stdout.write(`MCP    http://${options.host}:${options.port}/mcp\n`);
  logger.info(
    `서버 기동 MCP=${options.host}:${options.port} 관리=${ADMIN_HOST}:${options.adminPort}`,
  );

  return {
    close: async () => {
      await new Promise<void>((resolve) => mcpServer.close(() => resolve()));
    },
  };
}

function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.removeListener('error', reject);
      resolve();
    });
  });
}
```

`main.ts`:

```ts
/**
 * CLI 진입점.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** CLI 인자. 새 인자는 parseArgs() 에 더하고 serve() 로
 * 넘긴다.
 *
 * **깨면 안 되는 것.** 실제 시계를 만드는 곳은 여기뿐이다. 다른 모듈은
 * clock 을 주입받는다.
 */

import { parseArgs as nodeParseArgs } from 'node:util';

import { DEFAULTS, serve } from './app.js';
import { configureLogging, type Clock } from './logging.js';

export interface Options {
  host: string;
  port: number;
  adminPort: number;
  staleAfter: number;
  logDir: string | null;
  logRetentionDays: number;
}

export function parseArgs(argv: string[]): Options {
  const { values } = nodeParseArgs({
    args: argv,
    options: {
      host: { type: 'string' },
      port: { type: 'string' },
      'admin-port': { type: 'string' },
      'stale-after': { type: 'string' },
      'log-dir': { type: 'string' },
      'log-retention-days': { type: 'string' },
    },
  });

  const retention = Number(values['log-retention-days'] ?? 3);
  if (!Number.isInteger(retention) || retention <= 0) {
    // 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
    throw new Error('--log-retention-days 는 1 이상의 정수여야 한다');
  }

  return {
    host: values.host ?? DEFAULTS.host,
    port: Number(values.port ?? DEFAULTS.port),
    adminPort: Number(values['admin-port'] ?? DEFAULTS.adminPort),
    staleAfter: Number(values['stale-after'] ?? DEFAULTS.staleAfter),
    logDir: values['log-dir'] ?? null,
    logRetentionDays: retention,
  };
}

async function main(): Promise<number> {
  let options: Options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${(error as Error).message}\n`);
    return 2;
  }

  const clock: Clock = () => new Date();
  configureLogging({
    clock,
    sinks: [(line) => process.stdout.write(line + '\n')],
  });

  await serve({
    host: options.host,
    port: options.port,
    adminPort: options.adminPort,
    staleAfter: options.staleAfter,
    clock,
  });
  return 0;
}

main().then(
  (code) => {
    if (code !== 0) process.exit(code);
  },
  (error) => {
    process.stderr.write(`${String(error)}\n`);
    process.exit(1);
  },
);
```

- [ ] **Step 14: 빌드하고 유닛 테스트를 돌린다**

Run:
```bash
cd plugins/mcp-test/server-node && npm run build && npm test
```
Expected: 빌드 성공, 7 passed

- [ ] **Step 15: 노드 타깃으로 적합성 스위트를 돌린다**

Run:
```bash
cd /Users/gdsr/workspace/dev-exintueri/basic-mcp-py-server
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: 2 passed

- [ ] **Step 16: 파이썬 타깃이 여전히 통과하는지 본다 (회귀)**

Run:
```bash
uv run --directory plugins/mcp-test/conformance pytest -v --target=python
```
Expected: 2 passed

- [ ] **Step 17: 커밋**

```bash
git add plugins/mcp-test/server-node
git commit -m "feat(node): 노드 서버 골격과 인증, 접근 로그"
```

---

## Task 3: 슬라이스 1 — MCP 계약을 스위트에 적는다

노드에 아직 `/mcp` 가 없다. 파이썬으로 통과하고 노드로 실패하는 것을 확인하는 것이 이 태스크의 산출물이다.

**Files:**
- Modify: `plugins/mcp-test/conformance/test_mcp.py`

**Interfaces:**
- Consumes: Task 1 의 `server` 픽스처, `HEADERS`

- [ ] **Step 1: MCP 계약 테스트를 더한다**

`test_mcp.py` 에 이어 붙인다:

```python
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TOOL_NAMES = ["echo", "ping", "sessions", "whoami"]


async def _tools(url: str, headers: dict[str, str]):
    async with streamablehttp_client(url, headers=headers) as (read, write, get_sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            return get_sid(), listing.tools


def test_stateful_session_id_is_issued(server) -> None:
    session_id, _ = asyncio.run(_tools(server.mcp_url, HEADERS))
    # stateless 로 두면 이 값이 없다. session_view 의 mcp_session_id 가
    # 영원히 null 이 되므로 계약이 깨진다.
    assert session_id


def test_exactly_four_tools_are_exposed(server) -> None:
    _, tools = asyncio.run(_tools(server.mcp_url, HEADERS))
    assert sorted(t.name for t in tools) == TOOL_NAMES


def test_echo_returns_the_input_verbatim(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.call_tool("echo", {"text": "안녕 🌍"})

    result = asyncio.run(run())
    assert result.content[0].text == "안녕 🌍"


def test_ping_reports_process_shape(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.call_tool("ping", {})

    payload = json.loads(asyncio.run(run()).content[0].text)
    # 값이 아니라 형태만 본다. pid 는 두 런타임에서 다르다.
    assert isinstance(payload["pid"], int)
    assert isinstance(payload["uptime_seconds"], (int, float))
    assert isinstance(payload["session_count"], int)
    assert isinstance(payload["server_time"], str)


def test_whoami_reads_the_connection_id_from_the_header(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.call_tool("whoami", {})

    payload = json.loads(asyncio.run(run()).content[0].text)
    # SDK 의 콜백 인자 규약을 틀리면 여기서 잡힌다. 인자 없는 도구의 콜백은
    # (extra) 하나만 받는다 — (_args, extra) 로 쓰면 헤더를 못 읽는다.
    assert payload["instance_id"] == HEADERS["X-Client-Instance"]
    assert payload["known"] is True


def test_session_view_has_the_contracted_keys(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.call_tool("sessions", {})

    payload = json.loads(asyncio.run(run()).content[0].text)
    assert payload["count"] >= 1
    assert set(payload["sessions"][0]) == {
        "instance_id", "subject", "project", "label", "mcp_session_id",
        "connected_at", "last_seen", "call_count", "blocked", "stale",
    }
```

`test_mcp.py` 맨 위에 `import json` 을 더한다.

- [ ] **Step 2: 파이썬 타깃으로 전부 통과하는지 본다**

Run:
```bash
uv run --directory plugins/mcp-test/conformance pytest -v --target=python
```
Expected: 8 passed

여기서 실패하면 **스위트가 틀린 것이다.** 파이썬 서버는 이미 이 계약을 지키고 있다.

- [ ] **Step 3: 노드 타깃으로 실패하는지 본다**

Run:
```bash
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: 2 passed, 6 failed — 노드에 `/mcp` 라우트가 없다

- [ ] **Step 4: 커밋**

```bash
git add plugins/mcp-test/conformance/test_mcp.py
git commit -m "test(conformance): MCP 핵심의 계약을 적는다"
```

---

## Task 4: 슬라이스 1 — 노드 MCP 구현

**Files:**
- Create: `plugins/mcp-test/server-node/src/mcpServer.ts`, `src/mcpRoute.ts`
- Modify: `plugins/mcp-test/server-node/src/app.ts`

**Interfaces:**
- Consumes: `Registry`, `sessionView` (Task 2), `Clock` (Task 2)
- Produces: `mcpServer.ts` → `buildMcp(registry, startedAt, clock): McpServer`
- Produces: `mcpRoute.ts` → `mcpRoute(makeServer: () => McpServer): RequestHandler`

- [ ] **Step 1: `mcpServer.ts` 를 쓴다**

```ts
/**
 * McpServer 인스턴스와 노출 도구 4개.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** 도구를 더하고 빼는 곳은 buildMcp() 안이다.
 *
 * **깨면 안 되는 것.** 인자 없는 도구의 콜백은 (extra) 하나만 받는다.
 * SDK 의 executeToolHandler 가 inputSchema 유무로 갈리기 때문이다 —
 * 있으면 (args, extra), 없으면 (extra). 습관대로 (_args, extra) 라고 쓰면
 * extra 가 첫 인자에 들어가고 두 번째는 undefined 가 되어, whoami 가
 * 연결 ID 를 조용히 놓친다. 오류는 나지 않는다.
 *
 * 헤더는 extra.requestInfo.headers 에서 **소문자 키**로 읽는다.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

import { UNKNOWN_INSTANCE } from './auth.js';
import { getLogger, type Clock } from './logging.js';
import { Registry, sessionView } from './registry.js';

const logger = getLogger('call');

type Extra = { requestInfo?: { headers?: Record<string, string | string[] | undefined> } };

function instanceIdOf(extra: Extra | undefined): string {
  const raw = extra?.requestInfo?.headers?.['x-client-instance'];
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value || UNKNOWN_INSTANCE;
}

function textResult(payload: unknown) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(payload) }] };
}

/** 도구 호출을 한 줄 남긴다. 파이썬 쪽 _logged 데코레이터와 같은 역할이다. */
function logged<T>(name: string, extra: Extra | undefined, run: () => T): T {
  const started = process.hrtime.bigint();
  const instance = instanceIdOf(extra);
  try {
    const result = run();
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    logger.info(`tool=${name} instance=${instance} dur_ms=${ms.toFixed(0)} ok`);
    return result;
  } catch (error) {
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    logger.warn(
      `tool=${name} instance=${instance} dur_ms=${ms.toFixed(0)} ` +
        `error=${(error as Error).constructor.name}`,
    );
    throw error;
  }
}

export function buildMcp(registry: Registry, startedAt: Date, clock: Clock): McpServer {
  const mcp = new McpServer({ name: 'mcp-test-server', version: '0.1.0' });

  mcp.registerTool(
    'ping',
    {
      description:
        '서버 프로세스 정보를 반환한다. 여러 세션이 같은 pid를 보면 한 프로세스를 공유하는 것이다.',
    },
    (extra) =>
      logged('ping', extra as Extra, () => {
        const now = clock();
        return textResult({
          pid: process.pid,
          uptime_seconds: (now.getTime() - startedAt.getTime()) / 1000,
          session_count: registry.all().length,
          server_time: now.toISOString(),
        });
      }),
  );

  mcp.registerTool(
    'echo',
    { description: '받은 문자열을 그대로 돌려준다.', inputSchema: { text: z.string() } },
    (args, extra) =>
      logged('echo', extra as Extra, () => ({
        content: [{ type: 'text' as const, text: args.text }],
      })),
  );

  mcp.registerTool(
    'whoami',
    { description: '이 세션이 서버에 어떻게 보이는지 반환한다.' },
    (extra) =>
      logged('whoami', extra as Extra, () => {
        const instanceId = instanceIdOf(extra as Extra);
        const record = registry.get(instanceId);
        if (record === undefined) return textResult({ instance_id: instanceId, known: false });
        return textResult({ known: true, ...sessionView(record, registry, clock()) });
      }),
  );

  mcp.registerTool(
    'sessions',
    { description: '이 서버에 붙어 있는 모든 세션을 반환한다.' },
    (extra) =>
      logged('sessions', extra as Extra, () => {
        const now = clock();
        return textResult({
          count: registry.all().length,
          sessions: registry.all().map((r) => sessionView(r, registry, now)),
        });
      }),
  );

  return mcp;
}
```

- [ ] **Step 2: `mcpRoute.ts` 를 쓴다**

```ts
/**
 * 세션별 transport 라우팅.
 *
 * 파이썬은 mcp.streamable_http_app() 이 이 일을 내부에서 처리하지만, 노드
 * SDK 는 transport 인스턴스를 우리가 들고 있어야 한다.
 *
 * 이 Map 은 registry 와 **다른 것**이다. registry 는 X-Client-Instance 로
 * 세는 우리 개념이고, 이 Map 은 MCP 프로토콜의 Mcp-Session-Id 로 도는 SDK
 * 사정이다. 둘을 섞지 않는다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** 없는 세션에 대한 응답 코드와 본문.
 *
 * **깨면 안 되는 것.** sessionIdGenerator 를 undefined 로 두지 않는다.
 * 그것이 stateless 모드이고, 세션 ID 가 발급되지 않아 sessionView 의
 * mcp_session_id 가 영원히 null 이 된다.
 */

import { randomUUID } from 'node:crypto';
import type { Request, RequestHandler, Response } from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { isInitializeRequest } from '@modelcontextprotocol/sdk/types.js';

export function mcpRoute(makeServer: () => McpServer): RequestHandler {
  const transports = new Map<string, StreamableHTTPServerTransport>();

  return async (req: Request, res: Response): Promise<void> => {
    const raw = req.headers['mcp-session-id'];
    const sessionId = Array.isArray(raw) ? raw[0] : raw;

    if (sessionId !== undefined && transports.has(sessionId)) {
      await transports.get(sessionId)!.handleRequest(req, res, req.body);
      return;
    }

    if (sessionId === undefined && isInitializeRequest(req.body)) {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (id: string) => {
          transports.set(id, transport);
        },
      });
      transport.onclose = () => {
        if (transport.sessionId !== undefined) transports.delete(transport.sessionId);
      };
      await makeServer().connect(transport);
      await transport.handleRequest(req, res, req.body);
      return;
    }

    if (sessionId !== undefined) {
      res.status(404).json({ error: '알 수 없는 세션이다. 새 세션을 시작하라' });
      return;
    }
    res.status(400).json({ error: 'Mcp-Session-Id 헤더가 필요하다' });
  };
}
```

- [ ] **Step 3: `app.ts` 의 `buildMcpApp` 에 라우트를 붙인다**

`buildMcpApp` 을 아래로 바꾼다:

```ts
export function buildMcpApp(registry: Registry, startedAt: Date, clock: Clock): Express {
  const app = express();
  // 순서가 계약이다. 접근 로그가 바깥, 인증이 안쪽.
  app.use(accessLog());
  // express.json() 은 POST 에만 건다. GET(알림용 SSE 스트림)까지 걸면
  // transport 가 읽어야 할 스트림이 소진된다.
  app.post('/mcp', express.json());
  app.use(authMiddleware(registry, clock));

  const route = mcpRoute(() => buildMcp(registry, startedAt, clock));
  app.post('/mcp', route);
  app.get('/mcp', route);
  app.delete('/mcp', route);
  return app;
}
```

`serve()` 안의 호출을 `buildMcpApp(registry, options.clock() , options.clock)` 이 아니라, 시작 시각을 한 번만 찍도록 고친다:

```ts
  const startedAt = options.clock();
  const registry = new Registry(options.staleAfter);
  const mcpApp = buildMcpApp(registry, startedAt, options.clock);
```

`app.ts` 상단에 `import { buildMcp } from './mcpServer.js';` 와 `import { mcpRoute } from './mcpRoute.js';` 를 더한다.

- [ ] **Step 4: 빌드한다**

Run: `cd plugins/mcp-test/server-node && npm run build`
Expected: 종료 코드 0

- [ ] **Step 5: 노드 타깃으로 슬라이스 1 이 통과하는지 본다**

Run:
```bash
cd /Users/gdsr/workspace/dev-exintueri/basic-mcp-py-server
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: 8 passed

- [ ] **Step 6: `whoami` 테스트가 진짜로 무언가를 지키는지 확인한다**

이 저장소에서 가장 흔한 실패는 "통과하지만 아무것도 증명하지 않는 테스트" 다. 추론하지 말고 **실제로 깨 본다.**

`mcpServer.ts` 의 `whoami` 콜백을 `(extra) =>` 에서 `(_args: unknown, extra: Extra) =>` 로 잠깐 바꾸고 빌드한 뒤 스위트를 돌린다.

Expected: `test_whoami_reads_the_connection_id_from_the_header` 가 **FAIL**

확인했으면 되돌린다. 실패하지 않으면 그 테스트는 없는 것이다.

- [ ] **Step 7: 파이썬 회귀를 본다**

Run: `uv run --directory plugins/mcp-test/conformance pytest -q --target=python`
Expected: 8 passed

- [ ] **Step 8: 커밋**

```bash
git add plugins/mcp-test/server-node
git commit -m "feat(node): MCP 엔드포인트와 도구 4개"
```

---

## Task 5: 슬라이스 2 — 관리 API 계약과 파이썬 `runtime` 필드

**Files:**
- Create: `plugins/mcp-test/conformance/test_admin.py`
- Modify: `plugins/mcp-test/server/src/mcp_test_server/admin.py`
- Modify: `plugins/mcp-test/server/tests/test_admin.py`

**Interfaces:**
- Consumes: `server` 픽스처
- Produces: `/api/status` 응답에 `runtime: "python" | "node"`

- [ ] **Step 1: 파이썬 `admin.py` 에 `runtime` 을 더한다**

`build_admin_app` 시그니처에 인자를 더한다:

```python
def build_admin_app(
    registry: Registry,
    started_at: datetime,
    clock: Callable[[], datetime],
    mcp_endpoint: str,
    broadcaster: LogBroadcaster | None = None,
    log_file: Callable[[], Path | None] = lambda: None,
    should_stop: Callable[[], bool] = lambda: False,
    runtime: str = "python",
) -> Starlette:
```

`status()` 의 응답에 한 줄을 더한다:

```python
                "pid": os.getpid(),
                "runtime": runtime,
                "uptime_seconds": (now - started_at).total_seconds(),
```

`app.py` 의 `build_stack()` 에서 `build_admin_app(...)` 호출에 `runtime="python"` 을 넘길 필요는 없다 — 기본값이 그것이다. 기본값을 두는 이유는 이 서버가 파이썬 서버이기 때문이고, 노드가 자기 값을 쓰는 것과 무관하다.

- [ ] **Step 2: 파이썬 쪽 테스트를 더한다**

`server/tests/test_admin.py` 에 이어 붙인다:

```python
def test_status_reports_the_runtime() -> None:
    # 401 프로브로는 어느 런타임이 답했는지 알 수 없다. 기동 충돌 안내와
    # /mcp-test:server-status 가 이 필드에 의존한다.
    app = build_admin_app(
        Registry(),
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        mcp_endpoint="http://127.0.0.1:8765/mcp",
    )
    with TestClient(app) as client:
        assert client.get("/api/status").json()["runtime"] == "python"
```

이 파일의 기존 import 와 헬퍼를 그대로 쓴다. `TestClient` 나 `build_admin_app` 이 이미 import 돼 있지 않으면 더한다.

- [ ] **Step 3: 파이썬 테스트를 돌린다**

Run: `uv run --directory plugins/mcp-test/server pytest -q`
Expected: 전부 통과

- [ ] **Step 4: 관리 API 계약 스위트를 쓴다**

`conformance/test_admin.py`:

```python
"""슬라이스 2 — 관리 API 의 계약."""

from __future__ import annotations

import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from conftest import HEADERS

STATUS_KEYS = {
    "pid", "runtime", "uptime_seconds", "mcp_endpoint",
    "session_count", "sessions", "log_dir", "log_file",
}


async def _connect(url: str) -> None:
    """세션 하나를 만들어 레지스트리에 레코드를 남긴다."""
    async with streamablehttp_client(url, headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            await session.call_tool("ping", {})


def test_status_has_the_contracted_keys(server) -> None:
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert set(payload) == STATUS_KEYS
    assert payload["runtime"] == server.runtime
    assert isinstance(payload["pid"], int)


def test_status_lists_connected_sessions(server) -> None:
    asyncio.run(_connect(server.mcp_url))
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert payload["session_count"] == 1
    assert payload["sessions"][0]["instance_id"] == HEADERS["X-Client-Instance"]


def test_sessions_fragment_escapes_client_supplied_values(server) -> None:
    headers = {**HEADERS, "X-Client-Label": "<script>x</script>"}

    async def run():
        async with streamablehttp_client(server.mcp_url, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()

    asyncio.run(run())
    body = httpx.get(f"{server.admin_url}/fragments/sessions", timeout=5).text
    # 값은 클라이언트가 정한다. 날것으로 넣으면 관리 화면에 스크립트가 실린다.
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body


def test_sessions_fragment_has_the_contracted_columns(server) -> None:
    body = httpx.get(f"{server.admin_url}/fragments/sessions", timeout=5).text
    for column in ("연결 ID", "subject", "project", "label", "연결 시각", "마지막 호출", "호출"):
        assert column in body


def test_block_then_unblock_round_trip(server) -> None:
    asyncio.run(_connect(server.mcp_url))
    instance = HEADERS["X-Client-Instance"]

    blocked = httpx.post(f"{server.admin_url}/api/sessions/{instance}/block", timeout=5)
    assert blocked.status_code == 200
    assert blocked.json() == {"instance_id": instance, "action": "block"}

    # 차단된 연결은 403 을 받는다.
    denied = httpx.post(server.mcp_url, headers=HEADERS, timeout=5)
    assert denied.status_code == 403

    unblocked = httpx.post(f"{server.admin_url}/api/sessions/{instance}/unblock", timeout=5)
    assert unblocked.status_code == 200


def test_block_on_unknown_instance_is_404(server) -> None:
    response = httpx.post(f"{server.admin_url}/api/sessions/nope/block", timeout=5)
    assert response.status_code == 404
    assert "error" in response.json()


def test_html_form_post_redirects_to_index(server) -> None:
    asyncio.run(_connect(server.mcp_url))
    instance = HEADERS["X-Client-Instance"]
    response = httpx.post(
        f"{server.admin_url}/api/sessions/{instance}/block",
        headers={"Accept": "text/html"},
        follow_redirects=False,
        timeout=5,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_index_page_renders(server) -> None:
    response = httpx.get(f"{server.admin_url}/", timeout=5)
    assert response.status_code == 200
    assert "MCP 테스트 서버" in response.text
```

- [ ] **Step 5: 파이썬으로 통과, 노드로 실패를 확인한다**

Run:
```bash
uv run --directory plugins/mcp-test/conformance pytest -v --target=python
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: python 16 passed / node 8 passed, 8 failed (관리 리스너가 아직 없다)

- [ ] **Step 6: 커밋**

```bash
git add plugins/mcp-test/server plugins/mcp-test/conformance
git commit -m "feat(admin): status 에 runtime 을 싣고 관리 API 계약을 적는다"
```

---

## Task 6: 슬라이스 2 — 노드 관리 API 구현

**Files:**
- Create: `plugins/mcp-test/server-node/src/admin.ts`
- Modify: `plugins/mcp-test/server-node/src/app.ts`

**Interfaces:**
- Produces: `admin.ts` → `buildAdminApp(options): Express`

- [ ] **Step 1: `admin.ts` 를 쓴다**

```ts
/**
 * 관리 포트 앱. 127.0.0.1 에만 바인딩되며 인증하지 않는다.
 *
 * 인증이 없는 이유는 브라우저가 URL 을 여는 것만으로 Authorization 헤더를
 * 붙일 수 없기 때문이다.
 *
 * 그 대가를 정확히 적어 둔다. 루프백 바인딩은 **다른 기계**를 막을 뿐이다.
 * 이 앱이 상대하려는 클라이언트가 같은 기계의 브라우저이므로, 사용자가 연
 * 아무 웹 페이지나 이 포트에 닿을 수 있다. Origin 도 Host 도 검사하지
 * 않으므로, 그 페이지가 폼을 자동 제출해 살아 있는 세션을 차단할 수 있고
 * DNS 리바인딩으로 /api/status 를 읽을 수도 있다. 로컬 테스트 도구라서
 * 막지 않기로 한 것이다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** HTML 템플릿과 라우트 목록. 폴링 주기도 여기 있다.
 *
 * **함께 바꿔야 하는 것.** 표의 열을 바꾸면 conformance 스위트의
 * test_sessions_fragment_has_the_contracted_columns 가 따라온다.
 *
 * **깨면 안 되는 것.** 세션에서 온 값은 반드시 escapeHtml() 을 거쳐 넣는다.
 * 그 값들은 클라이언트가 정한다.
 */

import express from 'express';
import type { Express, Request, Response } from 'express';

import { accessLog } from './access.js';
import { getLogger, type Clock } from './logging.js';
import { Registry, sessionView } from './registry.js';

const registryLogger = getLogger('registry');

// 세션 표를 다시 받아오는 주기(밀리초). 이 폴링 자체가 접근 로그에 한 줄을
// 남기고 그 줄이 다시 로그 패널로 방송되므로, 주기를 짧게 두면 사용자가 보고
// 있는 화면을 자기 소음으로 채운다.
const SESSION_POLL_MS = 30000;

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

export interface AdminOptions {
  registry: Registry;
  startedAt: Date;
  clock: Clock;
  mcpEndpoint: string;
  runtime: string;
}

export function buildAdminApp(options: AdminOptions): Express {
  const { registry, startedAt, clock, mcpEndpoint, runtime } = options;

  const snapshot = (): { now: Date; views: Record<string, unknown>[] } => {
    const now = clock();
    return { now, views: registry.all().map((r) => sessionView(r, registry, now)) };
  };

  const sessionsHtml = (): string => {
    const { now, views } = snapshot();
    const rows = views
      .map((v) => {
        const classes = [v.stale ? 'stale' : '', v.blocked ? 'blocked' : '']
          .filter(Boolean)
          .join(' ');
        const action = v.blocked ? 'unblock' : 'block';
        const actionLabel = v.blocked ? '차단 해제' : '차단';
        const id = escapeHtml(String(v.instance_id));
        return `<tr class="${classes}">
<td>${id}</td><td>${escapeHtml(String(v.subject))}</td>
<td>${escapeHtml(String(v.project))}</td><td>${escapeHtml(String(v.label))}</td>
<td>${escapeHtml(String(v.connected_at))}</td><td>${escapeHtml(String(v.last_seen))}</td>
<td>${String(v.call_count)}</td>
<td><form method="post" action="/api/sessions/${id}/${action}">
<button type="submit">${actionLabel}</button></form></td>
</tr>`;
      })
      .join('');

    const uptime = ((now.getTime() - startedAt.getTime()) / 1000).toFixed(0);
    return `<p>pid ${process.pid} · uptime ${uptime}s · MCP ${escapeHtml(mcpEndpoint)} · 세션 ${views.length}개</p>
<p class="note">차단하면 그 세션은 403을 받고, Claude Code가 headersHelper를
다시 실행해 <b>새 연결 ID로 되살아난다.</b> 레코드가 사라지고 새 줄이
나타나는 것이 정상이다.</p>
<table>
<tr><th>연결 ID</th><th>subject</th><th>project</th><th>label</th>
<th>연결 시각</th><th>마지막 호출</th><th>호출</th><th></th></tr>
${rows}
</table>`;
  };

  const app = express();
  app.use(accessLog());
  app.use(express.urlencoded({ extended: false }));

  app.get('/api/status', (_req: Request, res: Response) => {
    const { now, views } = snapshot();
    res.json({
      pid: process.pid,
      runtime,
      uptime_seconds: (now.getTime() - startedAt.getTime()) / 1000,
      mcp_endpoint: mcpEndpoint,
      session_count: views.length,
      sessions: views,
      log_dir: null,
      log_file: null,
    });
  });

  app.get('/fragments/sessions', (_req: Request, res: Response) => {
    res.type('html').send(sessionsHtml());
  });

  app.get('/', (_req: Request, res: Response) => {
    res.type('html').send(`<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>MCP 테스트 서버</title>
<style>
body { font-family: ui-monospace, monospace; margin: 2rem; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; }
.stale { color: #888; }
.blocked { background: #fee; }
.note { color: #666; font-size: .9rem; }
#log { background: #111; color: #ddd; padding: .8rem; height: 24rem;
       overflow-y: scroll; white-space: pre-wrap; margin-top: .5rem; }
</style>
</head>
<body>
<h1>MCP 테스트 서버</h1>
<div id="sessions">${sessionsHtml()}</div>
<h2>로그</h2>
<p class="note">파일 로깅이 아직 붙지 않았다.</p>
<pre id="log"></pre>
<script>
setInterval(async () => {
  try {
    const html = await (await fetch('/fragments/sessions')).text();
    document.getElementById('sessions').innerHTML = html;
  } catch (e) { /* 서버가 잠깐 없을 수 있다. 다음 주기에 다시 시도한다. */ }
}, ${SESSION_POLL_MS});
</script>
</body>
</html>`);
  });

  /** block 과 unblock 라우트를 같은 코드로 만든다. */
  const toggle = (action: 'block' | 'unblock') => (req: Request, res: Response): void => {
    const instanceId = req.params.instanceId as string;
    const changed = action === 'block' ? registry.block(instanceId) : registry.unblock(instanceId);
    if (!changed) {
      res.status(404).json({ error: `알 수 없는 연결 ID: ${instanceId}` });
      return;
    }
    registryLogger.info(`${action} instance=${instanceId}`);
    if ((req.headers['accept'] ?? '').includes('text/html')) {
      res.redirect(303, '/');
      return;
    }
    res.json({ instance_id: instanceId, action });
  };

  app.post('/api/sessions/:instanceId/block', toggle('block'));
  app.post('/api/sessions/:instanceId/unblock', toggle('unblock'));

  return app;
}
```

- [ ] **Step 2: `app.ts` 에서 관리 리스너를 띄운다**

`serve()` 안, MCP 리스너를 띄운 뒤에 더한다:

```ts
  const adminApp = buildAdminApp({
    registry,
    startedAt,
    clock: options.clock,
    mcpEndpoint: `http://${endpointHost(options.host)}:${options.port}/mcp`,
    runtime: 'node',
  });
  const adminServer = createServer(adminApp);
  await listen(adminServer, options.adminPort, ADMIN_HOST);

  process.stdout.write(`관리   http://${ADMIN_HOST}:${options.adminPort}/\n`);
```

`serve()` 의 반환값을 두 서버 모두 닫도록 고친다:

```ts
  return {
    close: async () => {
      await Promise.all([
        new Promise<void>((resolve) => mcpServer.close(() => resolve())),
        new Promise<void>((resolve) => adminServer.close(() => resolve())),
      ]);
    },
  };
```

상단에 `import { buildAdminApp } from './admin.js';` 를 더한다.

- [ ] **Step 3: 빌드하고 노드 타깃을 돌린다**

Run:
```bash
cd plugins/mcp-test/server-node && npm run build
cd /Users/gdsr/workspace/dev-exintueri/basic-mcp-py-server
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: 16 passed

`log_dir` 과 `log_file` 은 아직 `null` 이다. 스위트는 키의 **존재**만 보므로 통과한다. 슬라이스 3 이 값을 채운다.

- [ ] **Step 4: 이스케이프 테스트가 진짜로 지키는지 확인한다**

`admin.ts` 의 `escapeHtml` 호출 하나를 잠깐 지우고 빌드한 뒤 스위트를 돌린다.

Expected: `test_sessions_fragment_escapes_client_supplied_values` 가 **FAIL**

확인했으면 되돌린다.

- [ ] **Step 5: 파이썬 회귀를 본다**

Run: `uv run --directory plugins/mcp-test/conformance pytest -q --target=python`
Expected: 16 passed

- [ ] **Step 6: 커밋**

```bash
git add plugins/mcp-test/server-node
git commit -m "feat(node): 관리 리스너와 세션 표"
```

---

## Task 7: 슬라이스 3 — 로깅 계약을 스위트에 적는다

**Files:**
- Create: `plugins/mcp-test/conformance/test_logging.py`

- [ ] **Step 1: 로깅 계약 스위트를 쓴다**

```python
"""슬라이스 3 — 로그 줄과 파일의 계약.

카테고리로 필터링해서 우리 줄을 찾는다. 파이썬 쪽에는 uvicorn 의 error 와
파이썬 MCP SDK 의 streamable_http_manager, transport_security 가 섞이므로,
"모르는 카테고리가 있으면 실패" 로 쓰면 안 된다.
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from conftest import HEADERS

LINE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) "
    r"(?P<level>INFO |WARN |ERROR) "
    r"(?P<category>\S+)\s+"
    r"(?P<message>.*)$"
)

OUR_CATEGORIES = {"app", "http", "registry", "call"}


def our_lines(text: str, category: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        match = LINE.match(raw)
        if match and match.group("category") == category:
            out.append(match.group("message"))
    return out


def wait_for(handle, category: str, pattern: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in our_lines(handle.log_text(), category):
            if re.search(pattern, message):
                return message
        time.sleep(0.2)
    raise AssertionError(
        f"{category} 카테고리에서 {pattern!r} 을 찾지 못했다.\n로그:\n{handle.log_text()}"
    )


def test_log_file_is_named_by_port_and_date(server) -> None:
    files = list(server.log_dir.glob("mcp-test-server.*.log"))
    assert len(files) == 1, files
    assert re.fullmatch(
        rf"mcp-test-server\.{server.port}\.\d{{4}}-\d{{2}}-\d{{2}}\.log", files[0].name
    )


def test_startup_line_is_written_under_app(server) -> None:
    wait_for(server, "app", r"서버 기동")


def test_rejected_request_is_logged_with_reason(server) -> None:
    httpx.post(server.mcp_url, timeout=5)
    message = wait_for(server, "http", r"POST /mcp 401")
    assert "reason=blank-token" in message
    assert re.search(r"dur_ms=\d+", message)


def test_rejected_request_is_warn_level(server) -> None:
    httpx.post(server.mcp_url, timeout=5)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for raw in server.log_text().splitlines():
            match = LINE.match(raw)
            if match and match.group("category") == "http" and "401" in match.group("message"):
                assert match.group("level") == "WARN "
                return
        time.sleep(0.2)
    raise AssertionError(f"401 줄을 찾지 못했다:\n{server.log_text()}")


def test_token_is_masked_in_the_connected_line(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()

    asyncio.run(run())
    message = wait_for(server, "registry", r"^connected ")
    # 앞 두 글자 + U+2026 + sha256 앞 8자리. 'alice' 의 값이다.
    assert "subject=al…(sha256:2bd806c9)" in message
    assert "alice" not in message


def test_tool_call_is_logged_under_call(server) -> None:
    async def run():
        async with streamablehttp_client(server.mcp_url, headers=HEADERS) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                await session.call_tool("ping", {})

    asyncio.run(run())
    message = wait_for(server, "call", r"tool=ping")
    assert f"instance={HEADERS['X-Client-Instance']}" in message
    assert message.endswith(" ok")


def test_newlines_in_the_path_cannot_forge_a_log_line(server) -> None:
    # 경로는 클라이언트가 정하고 마스킹도 걸리지 않는다. 날것으로 남기면
    # 요청 하나로 진짜와 구별되지 않는 줄을 만들어 넣을 수 있다.
    httpx.request("POST", f"{server.admin_url}/api/status%0a2026-01-01T00:00:00Z", timeout=5)
    for raw in server.log_text().splitlines():
        match = LINE.match(raw)
        if match and match.group("category") in OUR_CATEGORIES:
            assert "\r" not in raw


def test_status_reports_the_log_file(server) -> None:
    payload = httpx.get(f"{server.admin_url}/api/status", timeout=5).json()
    assert payload["log_dir"] == str(server.log_dir)
    assert payload["log_file"].endswith(".log")


def test_log_stream_emits_new_lines(server) -> None:
    """SSE 스트림에 새 줄이 실시간으로 붙는지 본다."""
    with httpx.stream(
        "GET", f"{server.admin_url}/api/logs/stream", timeout=15
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        httpx.post(server.mcp_url, timeout=5)  # 401 줄 하나를 만든다
        for line in response.iter_lines():
            if line.startswith("data: ") and "401" in line:
                return
    raise AssertionError("스트림에서 401 줄을 받지 못했다")


def test_access_log_records_the_sse_connection_immediately(server) -> None:
    """SSE 는 끝나지 않는다. 완료 시점에 남기면 이 줄이 영영 안 생긴다."""
    with httpx.stream("GET", f"{server.admin_url}/api/logs/stream", timeout=15) as response:
        assert response.status_code == 200
        wait_for(server, "http", r"GET /api/logs/stream 200")
```

- [ ] **Step 2: 경로 우선순위와 보관 스윕을 스위트에 더한다**

이 둘은 서버를 특별한 방식으로 띄워야 하므로 `server` 픽스처를 쓰지 않는다. `conftest.py` 에 저수준 헬퍼를 더한다:

```python
@pytest.fixture
def spawn(request: pytest.FixtureRequest, tmp_path: Path):
    """서버를 임의의 인자·환경으로 띄우고 종료 코드와 출력을 돌려준다.

    server 픽스처와 달리 기동을 기다리지 않는다. 기동에 실패하는 경우까지
    관찰해야 하기 때문이다.
    """
    runtime = request.config.getoption("--target")
    _ensure_built(runtime)
    started: list[subprocess.Popen] = []

    def run(extra: list[str], env_extra: dict[str, str] | None = None, wait: float = 3.0):
        import os
        stdout_path = tmp_path / f"spawn-{len(started)}.out"
        with stdout_path.open("wb") as sink:
            proc = subprocess.Popen(
                [*base_command(runtime), *extra],
                stdout=sink,
                stderr=subprocess.STDOUT,
                env={**os.environ, **(env_extra or {})},
            )
        started.append(proc)
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass
        return proc, stdout_path.read_text(encoding="utf-8", errors="replace")

    yield run

    for proc in started:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
```

`test_logging.py` 에 더한다:

```python
def test_env_var_sets_the_log_dir(spawn, tmp_path) -> None:
    target = tmp_path / "from-env"
    target.mkdir()
    port, admin_port = free_port(), free_port()
    proc, _ = spawn(
        ["--port", str(port), "--admin-port", str(admin_port)],
        {"MCP_TEST_LOG_DIR": str(target)},
    )
    assert list(target.glob("mcp-test-server.*.log")), "환경 변수의 디렉토리에 쓰지 않았다"


def test_flag_beats_the_env_var(spawn, tmp_path) -> None:
    from_env = tmp_path / "env"
    from_flag = tmp_path / "flag"
    from_env.mkdir()
    from_flag.mkdir()
    port, admin_port = free_port(), free_port()
    spawn(
        ["--port", str(port), "--admin-port", str(admin_port), "--log-dir", str(from_flag)],
        {"MCP_TEST_LOG_DIR": str(from_env)},
    )
    assert list(from_flag.glob("mcp-test-server.*.log"))
    assert not list(from_env.glob("mcp-test-server.*.log"))


def test_startup_sweep_removes_stale_logs_but_spares_others(spawn, tmp_path) -> None:
    import os

    log_dir = tmp_path / "sweep"
    log_dir.mkdir()
    old = time.time() - 10 * 86400
    stale = log_dir / "mcp-test-server.9999.2020-01-01.log"
    unrelated = log_dir / "중요한파일.txt"
    stale.write_text("x", encoding="utf-8")
    unrelated.write_text("x", encoding="utf-8")
    os.utime(stale, (old, old))
    os.utime(unrelated, (old, old))

    port, admin_port = free_port(), free_port()
    spawn(["--port", str(port), "--admin-port", str(admin_port), "--log-dir", str(log_dir)])

    assert not stale.exists(), "오래된 로그가 남았다"
    # log_dir 은 사용자가 정한다. 홈 디렉토리를 가리켜도 안전해야 한다.
    assert unrelated.exists(), "패턴에 맞지 않는 파일을 지웠다"
```

`test_logging.py` 상단에 `from conftest import HEADERS, free_port` 로 고친다.

- [ ] **Step 3: CLI 계약을 스위트에 더한다**

`conformance/test_cli.py`:

```python
"""CLI 플래그의 계약. 서버가 뜨기 전에 끝나는 것들이다."""

from __future__ import annotations

from conftest import free_port


def test_zero_retention_is_rejected(spawn) -> None:
    # 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
    proc, output = spawn(["--log-retention-days", "0"])
    assert proc.returncode not in (None, 0), output


def test_negative_retention_is_rejected(spawn) -> None:
    proc, output = spawn(["--log-retention-days", "-1"])
    assert proc.returncode not in (None, 0), output


def test_non_loopback_host_prints_a_warning(spawn, tmp_path) -> None:
    """루프백 밖에 열면 경고한다. 이 서버의 인증은 아무 토큰이나 통과시킨다."""
    port, admin_port = free_port(), free_port()
    _proc, output = spawn(
        [
            "--host", "0.0.0.0",
            "--port", str(port),
            "--admin-port", str(admin_port),
            "--log-dir", str(tmp_path),
        ]
    )
    assert "경고" in output
    assert "0.0.0.0" in output
```

`--host 0.0.0.0` 은 실제로 루프백 밖에 바인딩한다. 방화벽이 물어볼 수 있으므로, 이 테스트가 환경에 따라 성가시면 `@pytest.mark.skipif` 가 아니라 **명시적인 마커**(`@pytest.mark.exposes_port`)를 달고 `-m "not exposes_port"` 로 거르게 한다. 조용한 skip 을 만들지 않는다.

- [ ] **Step 4: 파이썬으로 전부 통과하는지 본다**

Run: `uv run --directory plugins/mcp-test/conformance pytest -v --target=python`
Expected: 32 passed (`test_mcp` 8 + `test_admin` 8 + `test_logging` 13 + `test_cli` 3)

실패하는 항목이 있으면 **스위트가 틀린 것이다.** 파이썬 서버는 이미 이 계약을 지키고 있다. 파이썬 서버의 실제 동작에 맞춰 단언을 고친다.

- [ ] **Step 5: 노드로 실패하는지 본다**

Run: `uv run --directory plugins/mcp-test/conformance pytest -v --target=node`
Expected: 19 passed, 13 failed

`test_cli.py` 셋은 노드도 **통과한다** — `parseArgs` 의 보관 기간 검증과 `exposureWarning` 은 Task 2 에서 이미 만들었다. `test_logging.py` 13개가 실패한다. 파일 로깅과 SSE 가 아직 없다.

- [ ] **Step 6: 커밋**

```bash
git add plugins/mcp-test/conformance
git commit -m "test(conformance): 로그 줄과 파일, CLI 의 계약을 적는다"
```

---

## Task 8: 슬라이스 3 — 노드 로깅 구현

**Files:**
- Create: `plugins/mcp-test/server-node/src/logPaths.ts`, `src/logStream.ts`
- Modify: `plugins/mcp-test/server-node/src/logging.ts`, `src/admin.ts`, `src/app.ts`, `src/main.ts`
- Create: `plugins/mcp-test/server-node/tests/logPaths.test.ts`

**Interfaces:**
- Produces: `logPaths.ts` → `resolveLogDir({flag, env, settingsPath}): {dir: string, warnings: string[]}`, `logFileName(port, day): string`, `purgeLogs(dir, now, {maxAgeSeconds, keep}): {removed: number, warnings: string[]}`, `tailLines(path, {lines, maxBytes}): string[]`
- Produces: `logStream.ts` → `class LogBroadcaster { subscribe(): AsyncIterator, publish(line), unsubscribe(q), subscriberCount }`

- [ ] **Step 1: `logPaths.ts` 의 실패 테스트를 쓴다**

`tests/logPaths.test.ts`:

```ts
import { mkdtempSync, writeFileSync, utimesSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { logFileName, purgeLogs } from '../src/logPaths.js';

describe('logFileName', () => {
  it('포트와 날짜로 이름을 만든다', () => {
    expect(logFileName(8765, new Date('2026-07-26T10:00:00Z'))).toBe(
      'mcp-test-server.8765.2026-07-26.log',
    );
  });
});

describe('purgeLogs', () => {
  it('패턴에 맞지 않는 파일은 건드리지 않는다', () => {
    // log_dir 은 사용자가 정한다. 홈 디렉토리를 가리켜도 안전해야 한다.
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const old = new Date('2020-01-01T00:00:00Z');

    writeFileSync(join(dir, 'mcp-test-server.8765.2020-01-01.log'), 'x');
    writeFileSync(join(dir, '중요한파일.txt'), 'x');
    for (const name of readdirSync(dir)) {
      utimesSync(join(dir, name), old, old);
    }

    const { removed } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'), {
      maxAgeSeconds: 259200,
      keep: null,
    });

    expect(removed).toBe(1);
    expect(readdirSync(dir)).toEqual(['중요한파일.txt']);
  });

  it('열려 있는 파일은 남긴다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const old = new Date('2020-01-01T00:00:00Z');
    const keep = join(dir, 'mcp-test-server.8765.2020-01-01.log');
    writeFileSync(keep, 'x');
    utimesSync(keep, old, old);

    const { removed } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'), {
      maxAgeSeconds: 259200,
      keep,
    });

    expect(removed).toBe(0);
    expect(readdirSync(dir)).toEqual(['mcp-test-server.8765.2020-01-01.log']);
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test`
Expected: FAIL — `../src/logPaths.js` 를 찾을 수 없다

- [ ] **Step 3: `logPaths.ts` 를 쓴다**

```ts
/**
 * 로그 파일의 위치와 이름, 그리고 오래된 파일 청소.
 *
 * 여기 있는 함수들은 로깅이 준비되기 전에 돈다 — 디렉토리를 정해야 파일에
 * 쓸 수 있기 때문이다. 그래서 경고를 직접 남기지 않고 문자열 배열로
 * 돌려주고, 호출자가 로깅이 준비된 뒤에 남긴다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** DEFAULT_LOG_DIR, logFileName() 의 형식,
 * MAX_AGE_SECONDS 기본값.
 *
 * **함께 바꿔야 하는 것.** LOG_PATTERN 과 logFileName() 은 한 쌍이다.
 * 한쪽만 바꾸면 청소가 아무것도 찾지 못해 로그가 영영 쌓인다 — 오류는
 * 나지 않는다. PLUGIN_ID_PREFIX 는 플러그인 쪽 plugin.json 의 name 과
 * 맞물린다.
 *
 * **깨면 안 되는 것.** purgeLogs 가 LOG_PATTERN 에 맞는 파일만, 비재귀로
 * 보는 것. log_dir 은 사용자가 정하므로 홈 디렉토리를 가리킬 수도 있다 —
 * 패턴을 넓히거나 재귀로 바꾸면 남의 파일을 지운다.
 */

import {
  closeSync, fstatSync, openSync, readdirSync, readFileSync, readSync, statSync, unlinkSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

export const DEFAULT_LOG_DIR = join(homedir(), '.mcp-test-server', 'logs');
export const MAX_AGE_SECONDS = 259200; // 72시간
const LOG_PATTERN = /^mcp-test-server\..*\.log$/;

// 플러그인 ID는 <plugin-name>@<marketplace-name> 이다. 서버는 자기가 어느
// 마켓플레이스에서 설치됐는지 알 수 없으므로 접두사로만 맞춘다.
const PLUGIN_ID_PREFIX = 'mcp-test@';
export const DEFAULT_SETTINGS_PATH = join(homedir(), '.claude', 'settings.json');

/**
 * 사용자가 준 경로 문자열을 한 형태로 정규화한다.
 *
 * 물결표를 펴지 않으면 홈이 아니라 현재 디렉토리 아래에 '~' 라는 이름의
 * 디렉토리를 만들고 거기에 로그를 쌓는다.
 */
function clean(value: string): string {
  const expanded = value.startsWith('~') ? join(homedir(), value.slice(1)) : value;
  return resolve(expanded);
}

function fromSettings(settingsPath: string): { dir: string | null; warnings: string[] } {
  let raw: string;
  try {
    raw = readFileSync(settingsPath, 'utf8');
  } catch {
    return { dir: null, warnings: [] }; // 파일이 없는 것은 정상이다
  }

  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return {
      dir: null,
      warnings: [`${settingsPath} 를 JSON 으로 읽지 못했다. 로그 경로 설정을 건너뛴다`],
    };
  }

  const configs = (data as Record<string, unknown>)?.['pluginConfigs'];
  if (typeof configs !== 'object' || configs === null) return { dir: null, warnings: [] };

  const matches = Object.keys(configs).filter((k) => k.startsWith(PLUGIN_ID_PREFIX)).sort();
  if (matches.length === 0) return { dir: null, warnings: [] };

  const warnings: string[] = [];
  const chosen = matches[0]!;
  if (matches.length > 1) {
    warnings.push(`플러그인 설정이 ${matches.length}개 발견됐다. ${chosen} 를 쓴다`);
  }

  const entry = (configs as Record<string, unknown>)[chosen];
  const options = (entry as Record<string, unknown>)?.['options'];
  if (typeof options !== 'object' || options === null) return { dir: null, warnings };

  const value = (options as Record<string, unknown>)['log_dir'];
  if (value === undefined || value === null) return { dir: null, warnings };
  if (typeof value !== 'string') {
    warnings.push(`플러그인 설정의 log_dir 이 문자열이 아니다: ${JSON.stringify(value)}`);
    return { dir: null, warnings };
  }
  if (!value.trim()) {
    warnings.push('플러그인 설정의 log_dir 이 비어 있다');
    return { dir: null, warnings };
  }
  return { dir: clean(value), warnings };
}

/** 로그 디렉토리를 정한다. 앞이 이긴다: --log-dir > $MCP_TEST_LOG_DIR > settings.json > 기본값 */
export function resolveLogDir(options: {
  flag: string | null;
  env: string | undefined;
  settingsPath?: string;
}): { dir: string; warnings: string[] } {
  if (options.flag && options.flag.trim()) return { dir: clean(options.flag), warnings: [] };
  if (options.env && options.env.trim()) return { dir: clean(options.env), warnings: [] };

  const { dir, warnings } = fromSettings(options.settingsPath ?? DEFAULT_SETTINGS_PATH);
  if (dir !== null) return { dir, warnings };
  return { dir: DEFAULT_LOG_DIR, warnings };
}

export function logFileName(port: number, day: Date): string {
  const iso = day.toISOString().slice(0, 10);
  return `mcp-test-server.${port}.${iso}.log`;
}

export function purgeLogs(
  logDir: string,
  now: Date,
  options: { maxAgeSeconds?: number; keep?: string | null } = {},
): { removed: number; warnings: string[] } {
  const maxAge = options.maxAgeSeconds ?? MAX_AGE_SECONDS;
  const keep = options.keep ? resolve(options.keep) : null;
  const cutoff = now.getTime() / 1000 - maxAge;

  let entries: string[];
  try {
    entries = readdirSync(logDir).filter((name) => LOG_PATTERN.test(name)).sort();
  } catch {
    return { removed: 0, warnings: [] };
  }

  let removed = 0;
  const warnings: string[] = [];
  for (const name of entries) {
    const path = join(logDir, name);
    if (keep !== null && resolve(path) === keep) continue;
    try {
      const info = statSync(path);
      if (!info.isFile()) continue;
      if (info.mtimeMs / 1000 >= cutoff) continue;
      unlinkSync(path);
    } catch (error) {
      warnings.push(`오래된 로그 ${path} 를 지우지 못했다: ${String(error)}`);
      continue;
    }
    removed += 1;
  }
  return { removed, warnings };
}

/** 파일 끝에서 최대 maxBytes 를 읽어 마지막 lines 줄을 돌려준다. */
export function tailLines(
  path: string,
  options: { lines?: number; maxBytes?: number } = {},
): string[] {
  const wanted = options.lines ?? 200;
  const maxBytes = options.maxBytes ?? 65536;
  let fd: number | undefined;
  try {
    fd = openSync(path, 'r');
    const size = fstatSync(fd).size;
    const start = Math.max(0, size - maxBytes);
    const length = size - start;
    const buffer = Buffer.alloc(length);
    readSync(fd, buffer, 0, length, start);
    let text = buffer.toString('utf8');
    // 잘린 첫 줄은 반쪽이라 버린다.
    if (size > maxBytes) text = text.slice(text.indexOf('\n') + 1);
    return text.split('\n').filter((l) => l !== '').slice(-wanted);
  } catch {
    return [];
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}
```

`dirname` 이 필요한 곳(`admin.ts`)은 `node:path` 에서 직접 import 한다. 이 모듈이 재수출하지 않는다.

- [ ] **Step 4: 유닛 테스트가 통과하는지 본다**

Run: `npm test`
Expected: 전부 통과

- [ ] **Step 5: `logStream.ts` 를 쓴다**

```ts
/**
 * 로그 줄을 SSE 구독자에게 fan-out 한다.
 *
 * 파일을 다시 읽지 않는다. 로거의 sink 에서 바로 밀기 때문에 파일 회전은
 * 스트림과 무관하고, 파일 로깅이 꺼져 있어도 스트림은 동작한다.
 *
 * ## 응용할 때
 *
 * 포크해도 대개 그대로 둔다. 고친다면 maxQueue 정도다.
 *
 * **깨면 안 되는 것.** 큐가 가득 차면 오래된 것부터 버린다. 느린 브라우저가
 * 서버를 세우면 안 된다. 그리고 publish() 는 어떤 경우에도 예외를 내지
 * 않는다 — 여기서 터지면 이 기능의 존재 이유인 크래시 줄이 사라진다.
 */

export class Subscriber {
  readonly queue: string[] = [];
  private waiter: (() => void) | null = null;

  push(line: string, maxQueue: number): void {
    if (this.queue.length >= maxQueue) this.queue.shift();
    this.queue.push(line);
    const waiter = this.waiter;
    this.waiter = null;
    waiter?.();
  }

  /** 줄이 생길 때까지 기다린다. timeoutMs 안에 없으면 빈 배열. */
  async drain(timeoutMs: number): Promise<string[]> {
    if (this.queue.length > 0) return this.queue.splice(0);
    await new Promise<void>((resolve) => {
      this.waiter = resolve;
      setTimeout(() => {
        if (this.waiter === resolve) {
          this.waiter = null;
          resolve();
        }
      }, timeoutMs);
    });
    return this.queue.splice(0);
  }
}

export class LogBroadcaster {
  private subscribers = new Set<Subscriber>();

  constructor(private maxQueue = 1000) {}

  get subscriberCount(): number {
    return this.subscribers.size;
  }

  subscribe(): Subscriber {
    const subscriber = new Subscriber();
    this.subscribers.add(subscriber);
    return subscriber;
  }

  unsubscribe(subscriber: Subscriber): void {
    this.subscribers.delete(subscriber);
  }

  publish(line: string): void {
    for (const subscriber of this.subscribers) {
      try {
        subscriber.push(line, this.maxQueue);
      } catch {
        // 한 구독자가 실패해도 나머지에는 민다.
      }
    }
  }
}
```

- [ ] **Step 6: `logging.ts` 에 일별 파일 sink 를 더한다**

`logging.ts` 끝에 더한다:

```ts
import { appendFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { logFileName } from './logPaths.js';

/**
 * 하루 한 파일. 날짜 경계는 주입된 시계로 판단한다.
 *
 * 쓰기 실패를 삼킨다. 로그 실패가 요청 처리를 통째로 죽이면 안 된다 —
 * 이 sink 는 접근 로그 미들웨어와 모든 도구 호출 안에서 돈다.
 */
export function dailyFileSink(
  logDir: string,
  port: number,
  clock: Clock,
): { sink: Sink; currentPath: () => string } {
  let day = clock().toISOString().slice(0, 10);
  let path = join(logDir, logFileName(port, clock()));

  return {
    sink: (line: string) => {
      const today = clock().toISOString().slice(0, 10);
      if (today !== day) {
        day = today;
        path = join(logDir, logFileName(port, clock()));
      }
      try {
        appendFileSync(path, line + '\n', 'utf8');
      } catch {
        // 삼킨다. 이유는 위 주석에 있다.
      }
    },
    currentPath: () => path,
  };
}

export function ensureLogDir(logDir: string): boolean {
  try {
    mkdirSync(logDir, { recursive: true });
    return true;
  } catch (error) {
    process.stderr.write(
      `경고: 로그 디렉토리 ${logDir} 를 쓸 수 없다 (${String(error)}). 파일 로깅 없이 계속한다.\n`,
    );
    return false;
  }
}
```

`Sink` 타입을 `export type Sink = (line: string) => void;` 로 바꿔 외부에서 쓸 수 있게 한다.

- [ ] **Step 7: `admin.ts` 에 로그 라우트를 더한다**

`AdminOptions` 에 `broadcaster: LogBroadcaster | null`, `logFile: () => string | null`, `shouldStop: () => boolean` 을 더하고, `/api/status` 의 `log_dir` / `log_file` 을 실제 값으로 채운다:

```ts
    const path = logFile();
    res.json({
      // ...
      log_dir: path === null ? null : dirname(path),
      log_file: path,
    });
```

SSE 라우트를 더한다:

```ts
  app.get('/api/logs/stream', async (req: Request, res: Response) => {
    if (broadcaster === null) {
      res.status(503).json({ error: '로그 스트림이 꺼져 있다' });
      return;
    }
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });

    const subscriber = broadcaster.subscribe();
    let closed = false;
    req.on('close', () => {
      closed = true;
    });

    try {
      let idle = 0;
      while (!closed && !shouldStop()) {
        // 1초씩 깨어나는 이유는 하트비트가 아니라 종료다. 15초를 통째로
        // 기다리면 그 사이에 시작된 종료를 최대 15초 동안 못 본다.
        const lines = await subscriber.drain(1000);
        if (lines.length === 0) {
          idle += 1;
          if (idle >= 15) {
            idle = 0;
            res.write(': ping\n\n'); // 유휴 연결이 끊기지 않게 하는 주석 하트비트
          }
          continue;
        }
        idle = 0;
        for (const line of lines) {
          // 트레이스백은 여러 줄이다. 줄마다 data: 를 붙이지 않으면 SSE
          // 프레이밍이 깨진다.
          const payload = line.split('\n').map((part) => `data: ${part}\n`).join('');
          res.write(payload + '\n');
        }
      }
    } finally {
      broadcaster.unsubscribe(subscriber);
      res.end();
    }
  });
```

인덱스 페이지의 로그 패널에 백필과 `EventSource` 를 붙인다. `<pre id="log">` 와 그 위 `<p class="note">` 를 아래로 바꾼다:

```ts
    const path = logFile();
    const note = path === null
      ? '파일 로깅이 꺼져 있다. 아래는 이 연결 이후의 로그만 보여준다.'
      : `${escapeHtml(path)} · 최근 200줄`;
    const backfill = path === null ? '' : escapeHtml(tailLines(path).join('\n'));
```

그리고 템플릿 안에서:

```html
<p class="note">${note}</p>
<pre id="log">${backfill}</pre>
```

`<script>` 안, 세션 폴링 뒤에 더한다:

```js
const box = document.getElementById('log');
box.scrollTop = box.scrollHeight;
new EventSource('/api/logs/stream').onmessage = (event) => {
  // 맨 아래를 보고 있을 때만 따라간다. 위로 올려 읽는 중이면 방해하지 않는다.
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent += event.data + '\n';
  if (atBottom) box.scrollTop = box.scrollHeight;
};
```

`admin.ts` 상단에 `import { dirname } from 'node:path';` 와 `import { tailLines } from './logPaths.js';` 를 더한다.

파이썬 쪽 `_PAGE` 는 `str.format()` 을 쓰느라 CSS·JS 의 중괄호가 전부 이중이지만, TS 템플릿 리터럴에는 그 제약이 없다. `${` 만 escape 하면 된다.

- [ ] **Step 8: `main.ts` 와 `app.ts` 를 배선한다**

`main.ts` 상단의 import 를 아래로 바꾼다:

```ts
import { parseArgs as nodeParseArgs } from 'node:util';

import { DEFAULTS, serve } from './app.js';
import {
  configureLogging, dailyFileSink, ensureLogDir, getLogger, type Clock, type Sink,
} from './logging.js';
import { resolveLogDir } from './logPaths.js';
import { LogBroadcaster } from './logStream.js';
```

Task 2 에서 쓴 `configureLogging({ clock, sinks: [...] })` 호출을 아래로 **대체한다**:

```ts
  const { dir: logDir, warnings } = resolveLogDir({
    flag: options.logDir,
    env: process.env['MCP_TEST_LOG_DIR'],
  });

  const broadcaster = new LogBroadcaster();
  const sinks: Sink[] = [(line) => broadcaster.publish(line)];
  let currentPath: (() => string) | null = null;

  if (ensureLogDir(logDir)) {
    const file = dailyFileSink(logDir, options.port, clock);
    sinks.push(file.sink);
    currentPath = file.currentPath;
  }
  configureLogging({ clock, sinks });

  // 경로를 정하는 동안에는 남길 곳이 없었다. 준비된 뒤에 남긴다.
  for (const message of warnings) getLogger('app').warn(message);
```

`serve()` 호출에 네 값을 더한다:

```ts
  await serve({
    host: options.host,
    port: options.port,
    adminPort: options.adminPort,
    staleAfter: options.staleAfter,
    clock,
    broadcaster,
    logDir: currentPath === null ? null : logDir,
    logFile: () => (currentPath === null ? null : currentPath()),
    logMaxAgeSeconds: options.logRetentionDays * 86400,
  });
```

`ServeOptions` 에 대응 필드를 더한다:

```ts
export interface ServeOptions {
  host: string;
  port: number;
  adminPort: number;
  staleAfter: number;
  clock: Clock;
  broadcaster: LogBroadcaster | null;
  logDir: string | null;
  logFile: () => string | null;
  logMaxAgeSeconds: number;
}
```

`serve()` 안, 관리 리스너를 띄운 뒤에 기동 출력과 청소를 더한다:

```ts
  if (options.logDir !== null) {
    process.stdout.write(`로그   ${options.logFile()}\n`);
    // 기동 직후 한 번 청소한다. 아래 주기 타이머는 10분 뒤에야 처음 돈다.
    const { warnings } = purgeLogs(options.logDir, options.clock(), {
      maxAgeSeconds: options.logMaxAgeSeconds,
      keep: options.logFile(),
    });
    for (const message of warnings) logger.warn(message);
  }

  const purgeTimer = setInterval(() => {
    const now = options.clock();
    const purged = registry.purge(now);
    if (purged > 0) getLogger('registry').info(`오래된 세션 ${purged}개를 정리했다`);
    if (options.logDir === null) return;
    const { removed, warnings } = purgeLogs(options.logDir, now, {
      maxAgeSeconds: options.logMaxAgeSeconds,
      keep: options.logFile(),
    });
    if (removed > 0) logger.info(`오래된 로그 ${removed}개를 지웠다`);
    for (const message of warnings) logger.warn(message);
  }, 600_000);
  // 이 타이머가 이벤트 루프를 붙들면 프로세스가 종료되지 않는다.
  purgeTimer.unref();
```

`close` 에 `clearInterval(purgeTimer)` 를 더하고, `buildAdminApp` 호출에 `broadcaster`, `logFile: options.logFile`, `shouldStop: () => shuttingDown` 을 넘긴다. `shuttingDown` 은 `serve()` 안의 `let shuttingDown = false;` 이고 `close` 가 맨 먼저 `true` 로 만든다 — 그래야 SSE 제너레이터가 스스로 끝나고 종료가 열린 연결에 막히지 않는다.

`app.ts` 상단에 `import { purgeLogs } from './logPaths.js';` 와 `import type { LogBroadcaster } from './logStream.js';` 를 더한다.

- [ ] **Step 9: 빌드하고 노드 타깃을 돌린다**

Run:
```bash
cd plugins/mcp-test/server-node && npm run build && npm test
cd /Users/gdsr/workspace/dev-exintueri/basic-mcp-py-server
uv run --directory plugins/mcp-test/conformance pytest -v --target=node
```
Expected: 32 passed

- [ ] **Step 10: SSE 접근 로그 테스트가 진짜로 지키는지 확인한다**

`access.ts` 의 `res.writeHead` 후킹을 `res.on('finish', ...)` 로 잠깐 바꾸고 빌드한 뒤 스위트를 돌린다.

Expected: `test_access_log_records_the_sse_connection_immediately` 가 **FAIL**

이것이 이 프로젝트에서 가장 놓치기 쉬운 함정이므로 반드시 눈으로 확인한다. 되돌린다.

- [ ] **Step 11: 파이썬 회귀를 본다**

Run: `uv run --directory plugins/mcp-test/conformance pytest -q --target=python`
Expected: 32 passed

- [ ] **Step 12: 커밋**

```bash
git add plugins/mcp-test/server-node
git commit -m "feat(node): 로그 파일과 SSE 스트림"
```

---

## Task 9: 커맨드, 훅, 문서

**Files:**
- Modify: `plugins/mcp-test/commands/server-start.md`
- Modify: `plugins/mcp-test/commands/server-status.md`
- Modify: `plugins/mcp-test/hooks/check-server.sh`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `server-start.md` 를 고친다**

```markdown
---
description: MCP 테스트 서버를 기동한다 (python 또는 node)
---

MCP 테스트 서버를 기동한다. **런타임을 반드시 명시한다.**

인자로 `python` 또는 `node` 를 받는다: `$ARGUMENTS`

1. 인자가 비어 있으면 `python` 과 `node` 중 무엇을 띄울지 사용자에게 묻고 멈춘다. 기본값을 임의로 고르지 않는다.
2. 인자가 두 값 중 어느 것도 아니면 두 런타임 이름을 알리고 멈춘다.
3. 이미 떠 있는지 확인한다. `curl -s --max-time 2 http://127.0.0.1:8766/api/status` 가 응답하면 이미 기동된 것이다. 응답의 `runtime` 과 `pid` 를 읽어 **어느 런타임이 떠 있는지** 알린다. 다른 런타임으로 바꾸려면 먼저 내려야 한다고 안내하고 멈춘다.
4. 떠 있지 않으면 백그라운드로 기동한다.

   `python` 인 경우:
   ```bash
   uv run --directory ${CLAUDE_PLUGIN_ROOT}/server mcp-test-server
   ```

   `node` 인 경우:
   ```bash
   cd ${CLAUDE_PLUGIN_ROOT}/server-node && npm install && npm run build && node dist/main.js
   ```

5. 기동되면 MCP 엔드포인트(`http://127.0.0.1:8765/mcp`)와 관리 페이지(`http://127.0.0.1:8766/`) 주소를 런타임과 함께 알린다.
6. 새 세션에서 서버에 붙으려면 `/mcp`로 연결 상태를 확인하라고 안내한다.

두 런타임은 같은 포트를 쓰므로 **동시에 띄울 수 없다.** MCP 클라이언트 쪽 설정(`.mcp.json`)은 어느 쪽이 떠 있든 그대로 동작한다.

포트를 바꾸려면 `--port`와 `--admin-port`를 쓴다. 이 경우 플러그인 설정의 `server_url`도 함께 바꿔야 한다.
```

- [ ] **Step 2: `server-status.md` 에 런타임을 더한다**

3번 항목의 표에 "서버 pid와 uptime" 을 "서버 런타임(`runtime`), pid, uptime" 으로 고친다.

- [ ] **Step 3: `check-server.sh` 의 안내 문구를 고친다**

```sh
  000)
    echo "MCP 테스트 서버($url)가 응답하지 않는다. /mcp-test:server-start python 또는 /mcp-test:server-start node 로 띄워라."
    ;;
```

`test_plugin_files.py::test_check_server_script_names_the_start_command_when_the_server_is_down` 은 `/mcp-test:server-start` 부분 문자열을 보므로 그대로 통과한다.

- [ ] **Step 4: 파이썬 플러그인 테스트를 돌린다**

Run: `uv run --directory plugins/mcp-test/server pytest -q`
Expected: 전부 통과

- [ ] **Step 5: `README.md` 를 고친다**

- 제목 아래 설명을 "하나의 파이썬 프로세스" 에서 "하나의 서버 프로세스(파이썬 또는 Node.js)" 로 고친다.
- "서버 기동" 절에 두 런타임의 명령을 나란히 적고, 같은 포트를 쓰므로 동시에 띄울 수 없다는 것과 `.mcp.json` 은 그대로라는 것을 적는다.
- "개발" 절에 세 명령을 적는다.

  ```bash
  # 파이썬 서버 단위 테스트
  uv run --directory plugins/mcp-test/server pytest -v

  # 노드 서버 단위 테스트
  cd plugins/mcp-test/server-node && npm test

  # 두 서버가 같은 계약을 지키는지 (적합성 스위트)
  uv run --directory plugins/mcp-test/conformance pytest -v --target=python
  uv run --directory plugins/mcp-test/conformance pytest -v --target=node
  ```

- "수동 검증 체크리스트" 에 항목을 하나 더한다: `[ ] node 로 띄운 뒤 같은 체크리스트를 다시 돌려 결과가 같은지 본다`
- "문서" 절에 이 설계 문서와 계획 문서 링크를 더한다.

- [ ] **Step 6: `CLAUDE.md` 의 주석 규약 범위를 명시한다**

"코드 주석" 절 첫 문단 뒤에 더한다:

```markdown
이 규약은 **두 런타임 모두에 적용된다.** 파이썬은 모듈 독스트링에,
노드(`plugins/mcp-test/server-node/`)는 파일 머리 JSDoc 블록에 같은 절을
둔다. 파이썬 쪽은 `tests/test_comment_conventions.py` 가, 노드 쪽은
`tests/commentConventions.test.ts` 가 빠뜨림을 잡는다.
```

- [ ] **Step 7: 노드 쪽 주석 규약 검사를 만든다**

`server-node/tests/commentConventions.test.ts`:

```ts
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = new URL('../src/', import.meta.url).pathname;
const SECTION = '## 응용할 때';

const modules = readdirSync(SRC).filter((name) => name.endsWith('.ts')).sort();

describe('주석 규약', () => {
  it('경로가 어긋나지 않았다', () => {
    // 경로가 틀리면 아래 테스트가 빈 목록을 돌며 조용히 통과한다.
    expect(modules.length).toBeGreaterThanOrEqual(9);
    expect(modules).toContain('app.ts');
  });

  it.each(modules)('%s 는 응용 방법을 적는다', (name) => {
    const text = readFileSync(join(SRC, name), 'utf8');
    const head = text.slice(0, text.indexOf('*/') + 2);
    expect(head.startsWith('/**')).toBe(true);
    expect(head).toContain(SECTION);
  });
});
```

- [ ] **Step 8: 전부 돌린다**

Run:
```bash
cd plugins/mcp-test/server-node && npm test && npm run build
cd /Users/gdsr/workspace/dev-exintueri/basic-mcp-py-server
uv run --directory plugins/mcp-test/server pytest -q
uv run --directory plugins/mcp-test/conformance pytest -q --target=python
uv run --directory plugins/mcp-test/conformance pytest -q --target=node
```
Expected: 전부 통과

- [ ] **Step 9: 커밋**

```bash
git add -A
git commit -m "docs: 두 런타임을 고르는 절차와 개발 명령"
```

---

## 완료 기준

- [ ] `--target=python` 과 `--target=node` 가 **같은 개수의 테스트를 통과**한다. 하나라도 skip 이면 완료가 아니다.
- [ ] `server-node/dist/` 를 지우고 스위트를 돌려도 통과한다 (픽스처가 빌드를 강제하는지 확인).
- [ ] `server-node/node_modules/` 를 지우고 `--target=node` 를 돌리면 **명확한 오류**로 멈춘다 (skip 이 아니다).
- [ ] Task 4·6·8 의 "진짜로 지키는지 확인한다" 스텝 셋을 **실제로 깨 보고** 되돌렸다.
- [ ] `/mcp-test:server-start` 를 인자 없이 부르면 되묻는다.
- [ ] 두 런타임을 번갈아 띄우고 같은 Claude Code 세션에서 `ping` 이 동작한다 (`.mcp.json` 변경 없이).
