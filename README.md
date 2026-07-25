# basic-mcp-py-server

여러 Claude Code 세션이 **하나의 파이썬 프로세스**에 MCP로 붙는 테스트 서버다.
이 저장소 자체가 플러그인 마켓플레이스이기도 하다.

설계 근거는 [설계 문서](docs/superpowers/specs/2026-07-25-mcp-test-server-plugin-design.md)에 있다.

## 왜 HTTP인가

stdio 전송은 세션마다 서버 프로세스를 새로 띄운다. 하나의 프로세스를 여러
세션이 공유하려면 HTTP여야 한다.

## 설치

```bash
claude plugin marketplace add dev-exintueri/basic-mcp-py-server
claude plugin install mcp-test@basic-mcp-py-server
```

설치 중 두 가지를 묻는다.

| 설정 | 기본값 | 설명 |
|---|---|---|
| MCP 서버 주소 | `http://127.0.0.1:8765` | 서버를 다른 포트로 띄웠다면 여기도 바꾼다 |
| 인증 토큰 | 없음 (필수) | 비어 있지 않으면 통과한다. 이 값이 관리 화면에 세션 식별자로 표시되므로 `alice` 처럼 알아볼 수 있는 값을 넣으면 편하다 |

## 서버 기동

플러그인 설치와 서버 기동은 별개다. 서버는 독립 프로세스로 직접 띄운다.

```bash
# 저장소에서 (개발 중)
uv run --directory plugins/mcp-test/server mcp-test-server

# 포트 변경
uv run --directory plugins/mcp-test/server mcp-test-server --port 9000 --admin-port 9001
```

Claude Code 안에서는 `/mcp-test:server-start` 로도 띄울 수 있다.

기동하면 두 주소가 열린다.

| | 주소 | 인증 |
|---|---|---|
| MCP | `http://127.0.0.1:8765/mcp` | 필수 |
| 관리 페이지 | `http://127.0.0.1:8766/` | 없음 (루프백 전용) |

관리 페이지의 바인딩 주소는 바꿀 수 없다. 인증이 없는 리스너이기 때문이다.

`--host 0.0.0.0` 처럼 MCP 리스너를 루프백 밖에 열면 안 된다. 이 서버의 인증은
비어 있지 않은 Bearer 토큰이면 무엇이든 통과시키므로, 그 포트에 닿을 수 있는
사람은 누구나 `sessions` 로 연결된 모든 세션의 프로젝트 경로와 토큰을 읽고
세션을 지울 수 있다. 그렇게 띄우면 서버가 stderr에 경고를 출력한다.

## 도구

| 도구 | 하는 일 |
|---|---|
| `ping` | 서버 pid, uptime, 세션 수 |
| `echo` | 받은 문자열을 그대로 반환 |
| `whoami` | 이 세션이 서버에 어떻게 보이는지 |
| `sessions` | 붙어 있는 모든 세션 |

권한 규칙에 쓸 전체 이름은 `mcp__plugin_mcp-test_test-server__ping` 형태다.
서버 키만 쓴 `mcp__test-server__*` 는 플러그인 번들 서버에 대해 동작하지 않는다.

## 수동 검증 체크리스트

**같은 디렉토리에서** 터미널 두 개를 띄우는 것이 중요하다. 서로 다른
프로젝트에서 띄우면 프로젝트 경로만으로 구분되어, 연결 ID가 실제로
동작하는지 확인되지 않는다.

- [ ] `claude plugin marketplace add ./` 로 이 저장소를 마켓플레이스로 등록하고 `claude plugin install mcp-test@basic-mcp-py-server` 로 설치한다
- [ ] 터미널 1에서 서버를 띄운다
- [ ] 터미널 2에서 `claude` 실행 후 `ping` 호출 → pid 기록
- [ ] 터미널 3에서 **같은 디렉토리로** `claude` 실행 후 `ping` 호출 → pid가 같은지 확인
- [ ] 둘 중 아무 쪽에서나 `sessions` 호출 → 세션 2개, `X-Client-Instance` 가 서로 다른지 확인
- [ ] 브라우저로 `http://127.0.0.1:8766/` 열기 → 같은 세션 2개가 보이는지 확인
- [ ] 한 세션을 차단 → 그 세션에서 도구를 호출하면 새 연결 ID로 되살아나는지 확인
- [ ] 서버를 끄고 새 `claude` 세션 시작 → `SessionStart` 훅이 기동 안내를 출력하는지 확인

세션에 사람이 읽을 이름을 붙이려면 `MCP_TEST_LABEL` 을 다르게 주고 실행한다.

```bash
MCP_TEST_LABEL=left  claude
MCP_TEST_LABEL=right claude
```

## 개발

```bash
uv run --directory plugins/mcp-test/server pytest -v
```

## 문서

- [설계 문서](docs/superpowers/specs/2026-07-25-mcp-test-server-plugin-design.md)
- [구현 계획](docs/superpowers/plans/2026-07-25-mcp-test-server-plugin.md)
- [Claude Code MCP 공식 문서 사본](docs/claude-base/README.md)
