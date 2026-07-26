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
