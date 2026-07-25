# MCP 테스트 서버 플러그인 설계

- 날짜: 2026-07-25
- 상태: 설계 확정, 구현 전
- 대상 저장소: `dev-exintueri/basic-mcp-py-server`

## 목표

여러 Claude Code 세션이 **하나의 파이썬 프로세스**에 MCP로 붙는 테스트 서버를 만들고, 이 저장소를 플러그인 마켓플레이스로 배포한다. 플러그인 설정 값이 MCP 서버 설정과 훅 프로세스로 전달되는 경로를 예시로 남기는 것이 부수 목표다.

이 서버는 테스트용이다. 실제 인증·권한·영속성을 구현하지 않는다.

## 요구사항

1. `mcp.json` 설정으로 기동되는 것이 아니라 **독립 프로세스**로 실행된다.
2. 여러 Claude 세션이 하나의 파이썬 서버에 연결된다.
3. 각 세션은 **같은** 서버 프로세스에 붙는다.
4. 인증이 필요하다. 테스트이므로 토큰이 **비어 있지 않으면**(공백 문자만 있어도 실패) 통과한다.
5. 이 저장소를 마켓플레이스로 추가해 플러그인으로 설치할 수 있다.
6. 플러그인 설정으로 MCP 환경을 구성하는 예시를 포함한다.
7. 브라우저로 서버 상태를 모니터링하고 관리하는 포트를 연다.

## 근거가 된 문서

이 설계의 Claude Code 측 동작은 모두 `docs/claude-base/`의 공식 문서 사본에서 확인했다. 추측이 아니다.

| 사실 | 출처 |
|---|---|
| HTTP(`streamable-http`)가 원격 서버의 권장 전송 방식이고, stdio는 로컬 프로세스를 띄운다 | `docs/claude-base/mcp.md:67`, `:105` |
| `url`이 있고 `type`이 없으면 설정 오류로 건너뛴다 | `docs/claude-base/mcp.md:85` |
| 플러그인 MCP 서버의 도구 이름은 `mcp__plugin_<플러그인>_<서버키>__<도구>` | `docs/claude-base/mcp.md:334` |
| `${CLAUDE_PLUGIN_ROOT}`·`${CLAUDE_PROJECT_DIR}`는 HTTP 서버의 `url`·`headers`에 치환된다 | `docs/claude-base/mcp.md:317` |
| `.mcp.json`의 `${VAR}`·`${VAR:-기본값}` 환경변수 확장은 `url`·`headers`에도 적용된다 | `docs/claude-base/mcp.md:441` |
| `${user_config.KEY}`가 MCP 서버 설정에 치환되고, 모든 값은 **훅 프로세스에** `CLAUDE_PLUGIN_OPTION_<KEY>` 환경변수로 전달된다 | `docs/claude-base/plugins-reference.md:581` |
| 셸에서 실행되는 필드는 `${user_config.*}`를 거부한다. 대안은 스크립트 안에서 `CLAUDE_PLUGIN_OPTION_<KEY>`를 읽는 것 | `docs/claude-base/plugins-reference.md:583`, `:587` |
| `userConfig` 값은 사용자 단위(`~/.claude/settings.json`)로 저장된다 | `docs/claude-base/plugins-reference.md:593` |
| 플러그인은 마켓플레이스 캐시(`~/.claude/plugins/cache`)로 복사된다 | `docs/claude-base/plugins-reference.md:769` |
| 마켓플레이스는 저장소 루트의 `.claude-plugin/marketplace.json`, 상대 경로 `source`는 마켓플레이스 루트 기준 | `https://code.claude.com/docs/en/plugin-marketplaces` |
| `headersHelper`는 **연결마다 한 번**, 세션 시작과 재연결 시점에 실행되며 stdout의 JSON을 연결 헤더에 병합한다. 캐싱은 없다 | `docs/claude-base/mcp.md:749`, `:783` |
| 도구 호출이 **401 또는 403**을 받으면 Claude Code가 헬퍼를 다시 실행해 새 헤더로 재연결하고 호출을 한 번 재시도한다 (v2.1.193 이상) | `docs/claude-base/mcp.md:785` |
| 플러그인이 제공하는 `headersHelper`는 `${user_config.*}`를 참조할 수 없다. 그 값은 `headers`에 넣으라고 문서가 지시한다 | `docs/claude-base/mcp.md:799` |
| `streamable_http_app()`은 `/mcp` 라우트와 lifespan을 포함한 Starlette 앱을 반환하고, 핸들러는 `Context`로 원본 요청 헤더에 접근한다 | `modelcontextprotocol/python-sdk` 문서 |
| **MCP `2026-07-28` 개정판에는 핸드셰이크도 세션도 없다.** 모든 요청이 독립 POST이고 `Mcp-Session-Id`가 발급되지 않는다. 세션 ID는 구버전 경로에만 존재한다 | `modelcontextprotocol/python-sdk` `docs/whats-new.md`, `docs/run/deploy.md` |

마켓플레이스 규격 문서(`plugin-marketplaces`)는 현재 `docs/claude-base/`에 없다. 이번 설계에서는 공식 문서를 직접 받아 확인했다. 미러에 추가할지는 별도 판단 사항이다.

## 결정과 그 이유

### 전송 방식: HTTP 고정

stdio는 세션마다 서버 프로세스를 새로 띄우므로 요구사항 2·3과 정면으로 배치된다. HTTP는 하나의 리스너에 여러 클라이언트가 붙으므로 요구사항이 전송 방식 선택만으로 충족된다. SSE는 공식 문서에서 deprecated다.

### 서버 위치: 플러그인 내부

파이썬 서버를 `plugins/mcp-test/server/`에 둔다. 플러그인이 캐시로 복사될 때 서버 소스도 함께 따라오므로, 설치만으로 서버를 손에 넣는다. 서버를 저장소 다른 위치에 두면 "플러그인 설치 + 저장소 clone" 두 단계가 되어 요구사항 5의 의미가 절반으로 준다.

대가는 캐시본을 수정해도 저장소에 반영되지 않는다는 점이다. 개발 중에는 저장소에서 직접 띄우고, 캐시본은 배포 검증용으로 쓴다.

### 기동 주체: 사용자가 직접 (+ 슬래시 커맨드 보조)

서버는 사용자가 직접 띄운다. 요구사항 1의 "독립 프로세스"를 가장 곧게 만족하고, 여러 세션이 하나를 공유하는지 눈으로 확인하기 쉽다. 편의를 위해 슬래시 커맨드를 함께 제공한다.

플러그인 `monitor`로 상시 기동하는 방식은 채택하지 않았다. 세션마다 기동을 시도하게 되어 "여러 세션이 하나의 프로세스를 공유한다"는 확인이 오히려 어려워진다.

### 관리 포트 분리

브라우저는 URL을 여는 것만으로 `Authorization` 헤더를 붙일 수 없다. 상태 페이지를 MCP와 같은 앱에 두면 인증 미들웨어에 경로 예외를 만들어야 하고, 이 서버가 보여주려는 인증 규칙 자체가 흐려진다. 포트를 나누면 규칙이 두 줄로 정리된다.

관리 포트는 **`127.0.0.1`에 고정 바인딩하며 설정으로 변경할 수 없다.** 공백만 아니면 통과하는 인증과 상태를 바꿀 수 있는 포트가 외부에 함께 열려서는 안 된다.

### 세션 식별은 `Mcp-Session-Id`가 아니라 `headersHelper`가 발급하는 연결 ID로

이 설계에서 가장 중요한 결정이다.

MCP `2026-07-28` 개정판에는 세션이 없다. 모든 요청이 독립 POST이고 `Mcp-Session-Id`가 발급되지 않는다. 따라서 전송 계층의 세션 ID로 클라이언트를 추적하는 설계는 클라이언트가 어느 프로토콜 버전을 쓰느냐에 따라 통째로 무너진다. 구버전 경로에서만 동작하고, 신버전에서는 모든 요청이 미지의 클라이언트로 보인다.

대신 `headersHelper`를 쓴다. 이 헬퍼는 **연결마다 한 번, 세션 시작과 재연결 시점에** 실행되므로, 여기서 난수 ID를 발급하면 그 연결의 모든 요청에 같은 값이 실린다. 프로토콜의 세션 유무와 무관하다.

부수 효과가 둘 있다.

- 식별자가 **요청 헤더**에만 존재하므로 응답 헤더를 가로챌 필요가 없다. 스트리밍 응답과 미들웨어가 얽히는 문제가 발생하지 않는다.
- 차단 응답을 403으로 하면 Claude Code가 헬퍼를 다시 실행해 **새 연결 ID로 재연결하고 호출을 재시도한다.** 재연결 테스트가 우리가 기대하는 동작이 아니라 문서에 명시된 자동 동작이 된다.

`Mcp-Session-Id`는 요청 헤더에 있으면 참고 정보로 기록하되, 식별에는 쓰지 않는다.

### 세션 차단은 자체 미들웨어로

SDK 내부 세션 매니저를 조작하는 것은 공개 API가 아니라 버전에 취약하고, 위 이유로 애초에 세션이 없을 수도 있다. 우리 미들웨어가 연결 ID 차단 목록을 관리하면 SDK 버전에도 프로토콜 버전에도 묶이지 않는다.

## 아키텍처

### 저장소 구조

```
basic-mcp-py-server/
├── .claude-plugin/
│   └── marketplace.json              마켓플레이스 카탈로그
├── plugins/
│   └── mcp-test/
│       ├── .claude-plugin/
│       │   └── plugin.json           플러그인 이름 + userConfig 선언
│       ├── .mcp.json                 HTTP 서버 등록 (치환 3종)
│       ├── commands/
│       │   ├── server-start.md       /mcp-test:server-start
│       │   └── server-status.md      /mcp-test:server-status
│       ├── hooks/
│       │   ├── hooks.json            SessionStart 훅 선언
│       │   └── check-server.sh       CLAUDE_PLUGIN_OPTION_* 를 읽는 예시
│       ├── scripts/
│       │   └── connection-id.sh      headersHelper — 연결마다 고유 ID 발급
│       └── server/
│           ├── pyproject.toml
│           ├── README.md
│           ├── src/mcp_test_server/
│           │   ├── __init__.py
│           │   ├── __main__.py       CLI 진입점
│           │   ├── app.py            두 ASGI 앱 동시 기동
│           │   ├── mcp_server.py     FastMCP 도구 정의
│           │   ├── auth.py           인증·차단 미들웨어
│           │   ├── registry.py       세션 레지스트리
│           │   └── admin.py          관리 포트 앱
│           └── tests/
├── docs/
└── README.md
```

### 프로세스 구성

한 프로세스 안에서 uvicorn 서버 두 개를 `asyncio.gather`로 동시에 돌린다.

| 리스너 | 기본 포트 | 바인딩 | 인증 | 내용 |
|---|---|---|---|---|
| MCP | 8765 | `127.0.0.1` (`--host`로 변경 가능) | 필수 | `POST /mcp` |
| 관리 | 8766 | `127.0.0.1` **고정** | 없음 | HTML 페이지 + JSON API |

MCP 앱은 `streamable_http_app()`이 반환하는 Starlette 앱을 최상위 앱으로 쓰고, 그 앞에 인증·세션 추적 미들웨어를 붙인다. 하위 앱으로 마운트하지 않으므로 `streamable_http_app()`에 내장된 lifespan이 그대로 동작한다.

### 모듈 책임

| 모듈 | 책임 | 의존 |
|---|---|---|
| `registry.py` | 세션 레코드와 차단 집합을 보유하는 **유일한 상태 보유자**. 등록·갱신·제거·stale 판정·차단·차단 해제 | 없음 |
| `auth.py` | Starlette 미들웨어. 인증 헤더 검사, 차단된 연결 거절, 요청 헤더에서 연결 ID 추출 후 레지스트리 갱신 | `registry` |
| `mcp_server.py` | FastMCP 인스턴스와 도구 4개. `Context`로 요청 헤더를 읽는다 | `registry` |
| `admin.py` | 관리 포트 Starlette 앱. HTML 페이지, `/api/status`, 차단 엔드포인트 | `registry` |
| `app.py` | 두 앱 조립과 동시 기동, 포트 충돌 처리, stale 스윕 태스크 | 위 전부 |
| `__main__.py` | CLI 인자 파싱 | `app` |

`registry.py` 외에는 상태를 갖지 않는다. 두 앱이 같은 이벤트 루프에서 돌므로 별도의 락은 두지 않는다.

### 용어

이 문서에서 **세션**은 하나의 Claude Code 연결을 뜻한다. MCP 프로토콜의 세션이 아니라, `headersHelper`가 발급한 연결 ID 하나에 대응하는 단위다. 사용자가 터미널에서 `claude`를 하나 띄우면 세션 하나다.

### 세션 레코드

```python
@dataclass
class SessionRecord:
    instance_id: str            # X-Client-Instance — 유일한 식별자
    subject: str                # Authorization Bearer 토큰 문자열 그대로
    project: str                # X-Client-Project (${CLAUDE_PROJECT_DIR})
    label: str                  # X-Client-Label (${MCP_TEST_LABEL:-unnamed})
    mcp_session_id: str | None  # 구버전 경로에서만 존재. 참고용
    connected_at: datetime
    last_seen: datetime
    call_count: int
    blocked: bool
```

`stale` 여부는 저장하지 않고 `last_seen`으로 그때그때 판정한다.

## 노출 도구

전체 이름은 `mcp__plugin_mcp-test_test-server__<도구>` 형태다. 권한 규칙·훅 매처에는 이 이름을 써야 한다. 서버 키만 쓴 `mcp__test-server__*`는 플러그인 번들 서버에 대해 동작하지 않는다.

| 도구 | 인자 | 반환 | 검증하는 것 |
|---|---|---|---|
| `ping` | 없음 | 서버 PID, uptime, 현재 세션 수 | 여러 세션이 같은 PID를 보면 프로세스 공유가 증명된다 |
| `echo` | `text: str` | 같은 문자열 | 인자 왕복 |
| `whoami` | 없음 | 내 연결 ID, subject, project, label, 연결 시각, 호출 수 | 헤더 4종이 실제로 서버에 도달했는지 |
| `sessions` | 없음 | 전체 세션 목록 (연결 ID, subject, project, label, 연결 시각, 마지막 호출, stale 여부) | 멀티세션 관찰 |

`sessions`는 토큰 문자열을 그대로 노출한다. 테스트 서버이고 토큰이 곧 식별자이므로 의도된 동작이다.

## 인증

### 값이 흐르는 경로

```
설치 시 사용자 입력
   ↓  userConfig (plugin.json)
~/.claude/settings.json  ·  auth_token은 Keychain
   ↓  ${user_config.*} 치환
.mcp.json headers
   ↓  HTTP 요청
auth.py 미들웨어: Bearer 뒤 문자열 strip() → 비어 있으면 401
```

### 플러그인 설정

```json
// plugins/mcp-test/.claude-plugin/plugin.json
{
  "name": "mcp-test",
  "description": "여러 Claude 세션이 하나의 파이썬 프로세스에 붙는 MCP 테스트 서버",
  "version": "0.1.0",
  "userConfig": {
    "server_url": {
      "type": "string",
      "title": "MCP 서버 주소",
      "description": "테스트 서버의 베이스 URL. 기본값은 로컬 기동 시의 주소",
      "default": "http://127.0.0.1:8765"
    },
    "auth_token": {
      "type": "string",
      "title": "인증 토큰",
      "description": "비어 있지 않으면 통과한다. 이 값이 관리 화면의 세션 식별자로 표시된다",
      "sensitive": true,
      "required": true
    }
  }
}
```

### MCP 서버 등록

```json
// plugins/mcp-test/.mcp.json
{
  "mcpServers": {
    "test-server": {
      "type": "http",
      "url": "${user_config.server_url}/mcp",
      "headers": {
        "Authorization":    "Bearer ${user_config.auth_token}",
        "X-Client-Project": "${CLAUDE_PROJECT_DIR}",
        "X-Client-Label":   "${MCP_TEST_LABEL:-unnamed}"
      },
      "headersHelper": "${CLAUDE_PLUGIN_ROOT}/scripts/connection-id.sh"
    }
  }
}
```

`headers` 한 곳에 세 가지 치환이 모두 들어간다 — 플러그인 설정, 경로 플레이스홀더, 환경변수 확장.

인증 토큰을 `headers`에 두고 `headersHelper`에 두지 않은 것은 의도적이다. 플러그인이 제공하는 헬퍼는 셸을 거치므로 `${user_config.*}`를 참조할 수 없고, 문서가 그 값은 `headers`에 넣으라고 명시한다 (`mcp.md:799`).

### 연결 ID 발급

```sh
# plugins/mcp-test/scripts/connection-id.sh
#!/bin/sh
id=$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')
printf '{"X-Client-Instance": "%s"}\n' "$(printf '%s' "$id" | tr -d '-' | cut -c1-12)"
```

헬퍼는 연결마다 한 번 실행되므로 이 값은 그 연결이 유지되는 동안 고정이고, 연결이 새로 맺어지면 바뀐다. `uuidgen`이 없는 환경을 위해 `python3` 대체 경로를 둔다 — 서버 자체가 Python을 요구하므로 둘 중 하나는 반드시 있다.

동적 헤더는 같은 이름의 정적 헤더를 덮어쓰지만, `X-Client-Instance`는 정적 `headers`에 없으므로 충돌하지 않는다.

### 왜 이 식별자가 필요한가

`userConfig` 값은 사용자 단위로 저장되므로 같은 머신의 모든 세션이 **같은 토큰**을 보낸다. `X-Client-Project`도 같은 프로젝트에서 띄운 두 세션이면 같다. 즉 헤더 치환만으로는 세션을 구분할 수 없다.

| 구분자 | 다른 프로젝트의 두 세션 | **같은 프로젝트의 두 세션** |
|---|---|---|
| `Authorization` | 같음 | 같음 |
| `X-Client-Project` | 다름 | **같음** |
| `X-Client-Label` | 사용자가 `MCP_TEST_LABEL`을 다르게 준 경우에만 다름 | 위와 같음 |
| `X-Client-Instance` | **다름** | **다름** |

`X-Client-Instance`만이 모든 경우에 세션을 구분한다. 사람이 읽을 이름을 붙이고 싶으면 `MCP_TEST_LABEL`을 세션별로 다르게 주고 `claude`를 실행한다.

### 검사 규칙

```
Authorization 헤더 없음                → 401
"Bearer " 접두사 없음                  → 401
Bearer 뒤 문자열이 strip() 후 빈 문자열 → 401
그 외                                  → 통과, 그 문자열이 subject
```

401 응답에는 `WWW-Authenticate: Bearer`를 붙인다.

## 플러그인 설정을 환경변수로 받는 예시

`${user_config.*}`는 셸에서 실행되는 필드에서 거부된다. 문서가 지정한 대안은 스크립트 안에서 `CLAUDE_PLUGIN_OPTION_<KEY>`를 읽는 것이다. `SessionStart` 훅으로 이 경로를 예시화한다.

```json
// plugins/mcp-test/hooks/hooks.json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-server.sh"
          }
        ]
      }
    ]
  }
}
```

`check-server.sh`는 `CLAUDE_PLUGIN_OPTION_SERVER_URL`을 환경변수로 읽어 서버 생존을 확인한다. 확인 방법은 **인증 없이 `/mcp`에 POST해서 401이 오는지** 보는 것이다. 401은 서버가 살아 있다는 것과 인증이 실제로 걸려 있다는 것을 동시에 증명하므로, 무인증 헬스체크 경로를 따로 뚫지 않아도 된다.

| 응답 | 판정 | 훅 출력 |
|---|---|---|
| `401` | 정상 | 없음 |
| 연결 실패 | 서버 미기동 | 기동 명령 안내 |
| 그 외 | 예상 밖 | 상태 코드와 함께 경고 |

훅은 어떤 경우에도 세션을 막지 않는다. 종료 코드는 항상 0이다.

## 슬래시 커맨드

커맨드는 프롬프트 파일이므로 환경변수를 직접 받지 않는다. 사람이 손으로 치는 명령을 줄이는 용도다.

| 커맨드 | 하는 일 |
|---|---|
| `/mcp-test:server-start` | 서버가 이미 떠 있는지 확인하고, 없으면 `${CLAUDE_PLUGIN_ROOT}/server`에서 기동한다. 기동 후 MCP 엔드포인트와 관리 페이지 주소를 알린다 |
| `/mcp-test:server-status` | 관리 포트의 `/api/status`를 조회해 세션 목록과 서버 정보를 요약한다 |

## 세션 추적

`auth.py` 미들웨어가 담당한다. SDK 내부 세션 매니저는 건드리지 않고, **요청 헤더만** 읽는다.

- 식별자는 요청 헤더 `X-Client-Instance`다. 모든 요청에 실려 오므로 초기화 요청을 특별 취급할 필요가 없고, 응답을 들여다볼 필요도 없다.
- 처음 보는 값이면 레코드를 만들고, 이미 있으면 `last_seen`과 `call_count`를 갱신한다.
- `Mcp-Session-Id`가 요청 헤더에 있으면 레코드에 기록한다. 구버전 경로에서만 채워지며, 식별에는 쓰지 않는다.
- `X-Client-Instance`가 없는 요청은 헬퍼가 없거나 실패한 경우다. 거절하지 않고 `unknown`으로 묶어 기록한다. 관리 페이지에 그렇게 표시되면 헬퍼 설정을 의심하라는 신호다.
- `DELETE /mcp`를 받으면 레코드를 제거한다.
- `last_seen`이 5분을 넘긴 세션은 **제거하지 않고** stale로 표시한다. 유휴 세션이 목록에서 사라지면 오히려 상태 파악이 어렵다. 24시간을 넘기면 스윕 태스크가 제거한다.

## 관리 포트

### 엔드포인트

| 메서드 | 경로 | 동작 |
|---|---|---|
| `GET` | `/` | 상태 HTML 페이지. 5초 자동 새로고침 |
| `GET` | `/api/status` | 서버 정보와 세션 목록 JSON |
| `POST` | `/api/sessions/{instance_id}/block` | 해당 세션 차단 |
| `POST` | `/api/sessions/{instance_id}/unblock` | 차단 해제 |

HTML 페이지는 프레임워크 없이 서버가 렌더링한다. 차단 버튼은 폼 POST다.

### 차단 동작

차단된 연결 ID의 MCP 요청에는 **`403 Forbidden`**을 반환한다.

Claude Code는 도구 호출이 401이나 403을 받으면 `headersHelper`를 다시 실행해 새 헤더로 재연결하고 호출을 한 번 재시도한다 (`mcp.md:785`). 헬퍼는 매번 새 ID를 발급하므로, 차단된 세션은 **새 연결 ID로 즉시 되살아난다.**

영구 차단이 아니라 재연결 경로를 테스트하는 수단이다. 관리 페이지에서 차단을 누르면 그 레코드는 곧 사라지고 새 레코드가 나타난다 — 이것이 정상 동작이며 화면에 그렇게 안내한다.

차단 상태를 유지해서 관찰하고 싶으면 차단 해제 전까지 해당 세션에서 도구를 호출하지 않으면 된다. 재시도는 도구 호출이 있어야 발생한다.

## 에러 처리

| 상황 | 서버 동작 | 사용자가 보는 것 |
|---|---|---|
| `Authorization` 없음 / 공백만 | `401` + `WWW-Authenticate: Bearer` | `/mcp`에서 연결 실패. 토큰이 계속 비어 있으면 재시도도 실패하고 인증 필요로 표시됨 |
| 차단된 연결 ID의 요청 | `403` | Claude Code가 헬퍼를 재실행해 새 연결 ID로 재연결 후 재시도 |
| `X-Client-Instance` 없음 | 통과 | `unknown`으로 기록. 관리 페이지에서 헬퍼 미설정 신호 |
| 서버 미기동 | — | 연결 거부. `SessionStart` 훅이 기동 방법 안내 |
| 포트 사용 중 | 기동 즉시 종료 (코드 1) | 어느 포트가 막혔는지 명시된 메시지 |
| 관리 포트 외부 접근 | — | 루프백 바인딩이라 도달 불가 |
| 알 수 없는 연결 ID로 차단 요청 | `404` + JSON 오류 | 관리 페이지에 메시지 |

도구 실행 중 예외는 FastMCP 기본 동작에 맡긴다. 별도로 감싸지 않는다.

## 테스트

| 층위 | 대상 | 방법 |
|---|---|---|
| 단위 | `registry` 등록·갱신·stale 판정·제거·차단 | 순수 함수 테스트 |
| 단위 | `auth` 미들웨어 — 헤더 없음/`Bearer` 없음/공백만/정상 | `httpx` ASGI 트랜스포트 |
| 단위 | 차단된 연결 ID → 403 | 위와 동일 |
| 단위 | `X-Client-Instance` 없는 요청 → `unknown`으로 기록 | 위와 동일 |
| 단위 | `connection-id.sh`가 유효한 JSON 한 줄을 내고, 두 번 실행하면 값이 다른지 | 스크립트 직접 실행 |
| 통합 | 관리 API `/api/status`, 차단·해제 | `httpx` ASGI 트랜스포트 |
| **인수** | **실제 MCP 클라이언트 2개를 서로 다른 `X-Client-Instance`로 같은 서버에 연결** → `sessions`에 둘 다 보이고 `ping`의 PID가 동일 | 서버를 실제 포트에 띄우고 MCP 파이썬 클라이언트로 접속 |
| 인수 | 차단된 연결의 도구 호출이 403을 받는지 | 위와 동일. Claude Code의 자동 재시도는 클라이언트 측 동작이므로 여기서는 서버 응답까지만 검증한다 |
| 수동 | **같은 디렉토리에서** `claude` 2개 실행 → `sessions` 2개, `X-Client-Instance` 상이 | 체크리스트를 README에 기록 |
| 수동 | 관리 페이지에서 차단 → 해당 세션이 새 연결 ID로 되살아나는지 | 위와 동일 |

인수 테스트가 이 프로젝트의 핵심이다. 요구사항 2·3이 실제로 성립하는지를 검증하는 유일한 테스트다.

수동 검증을 **같은 디렉토리**에서 하는 것이 중요하다. 서로 다른 프로젝트에서 띄우면 `X-Client-Project`만으로도 구분되어, 연결 ID가 실제로 동작하는지 확인되지 않는다.

## 배포와 사용

### 마켓플레이스 카탈로그

```json
// .claude-plugin/marketplace.json
{
  "name": "basic-mcp-py-server",
  "owner": { "name": "exintueri" },
  "description": "MCP 테스트 서버 플러그인",
  "plugins": [
    {
      "name": "mcp-test",
      "source": "./plugins/mcp-test",
      "description": "여러 Claude 세션이 하나의 파이썬 프로세스에 붙는 MCP 테스트 서버"
    }
  ]
}
```

### 설치

```bash
claude plugin marketplace add dev-exintueri/basic-mcp-py-server
claude plugin install mcp-test@basic-mcp-py-server
# 설치 중 auth_token, server_url 입력 프롬프트가 뜬다
```

### 기동

```bash
# 설치본
uv run --directory ~/.claude/plugins/cache/<...>/mcp-test/server mcp-test-server

# 개발 중 (저장소에서 직접)
uv run --directory plugins/mcp-test/server mcp-test-server

# 포트 변경
uv run --directory plugins/mcp-test/server mcp-test-server --port 9000 --admin-port 9001
```

기동하면 MCP 엔드포인트와 관리 페이지 주소를 출력한다.

### CLI 인자

| 인자 | 기본값 | 설명 |
|---|---|---|
| `--host` | `127.0.0.1` | MCP 리스너 바인딩 주소 |
| `--port` | `8765` | MCP 리스너 포트 |
| `--admin-port` | `8766` | 관리 리스너 포트 |
| `--stale-after` | `300` | stale 판정 기준 (초) |

관리 리스너의 바인딩 주소를 바꾸는 인자는 **제공하지 않는다.**

## 의존성

- Python 3.11 이상
- `uv`
- `mcp` (공식 파이썬 SDK), `uvicorn`, `starlette`
- 개발: `pytest`, `pytest-asyncio`, `httpx`

## 범위 밖

명시적으로 만들지 않는 것들이다.

- OAuth, 토큰 발급·검증·만료
- 세션 상태의 디스크 영속화 (프로세스가 죽으면 전부 사라진다)
- 세션 간 공유 데이터 저장소 (`sessions` 목록만으로 프로세스 공유가 증명되므로 불필요)
- 인증 검사 on/off 토글, 서버 원격 종료 (검증해야 할 인증 경로를 우회하는 스위치는 방해가 된다)
- TLS
- 여러 머신에서의 접속 (`--host`로 열 수는 있으나 지원 대상이 아니다)
