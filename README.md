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
| 인증 토큰 | 없음 (필수) | 비어 있지 않으면 통과한다. `alice` 처럼 알아볼 수 있는 별명을 넣는다 |

> 인증 토큰에 **진짜 자격 증명을 넣지 마라.** Claude Code는 이 값을
> `sensitive` 로 다뤄 화면에서 가리지만, 서버는 이 값을 그대로 세션 식별자
> (`subject`)로 관리 화면과 `sessions` 도구에 싣는다. 즉 **이 서버에 붙은
> 다른 모든 세션이 이 값을 읽는다.** 알아볼 수 있는 별명이면 충분하다.

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
| 관리 페이지 | `http://127.0.0.1:8766/` | 없음 (127.0.0.1 바인딩) |

관리 페이지의 바인딩 주소는 바꿀 수 없다. 인증이 없는 리스너이기 때문이다.

다만 루프백 바인딩이 막는 것은 **다른 기계**뿐이다. 이 페이지의 클라이언트가
같은 기계의 브라우저이므로, 사용자가 연 아무 웹 페이지나 이 포트에 요청을
보낼 수 있다. 그 페이지가 폼을 자동 제출해 살아 있는 세션을 차단할 수 있고,
DNS 리바인딩을 쓰면 `/api/status` 를 읽어 연결 ID, 프로젝트 경로, 서버 pid,
`subject` 로 표시되는 토큰까지 가져갈 수 있다. 로컬 테스트 도구라서 막지
않기로 한 것이니, 이 서버를 띄운 채로 신뢰할 수 없는 페이지를 열지 마라.

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

## 로그

서버는 뜬 채로 파일 하나에 로그를 남긴다.

- 기본 위치는 `~/.mcp-test-server/logs`, 파일명은
  `mcp-test-server.<포트>.<날짜>.log` 이다. 날짜가 바뀌면 새 파일로 넘어간다.
- 어느 디렉토리를 쓸지는 다음 순서로 정한다: `--log-dir` > `$MCP_TEST_LOG_DIR`
  > 플러그인 설정 `log_dir` > 기본값. **플러그인 설정을 바꾸면 서버를
  재기동해야 반영된다** — 서버가 이 값을 읽는 시점은 기동할 때뿐이다.
- 보관 기간은 기본 72시간(`--log-retention-days 3`)이고, 마지막 수정
  시각(mtime) 기준이다. 기동 시 한 번,
  이후 10분마다 오래된 파일을 지운다. `mcp-test-server.*.log` 패턴에 맞는
  파일만 지우므로, 로그 디렉토리로 홈 디렉토리를 가리켜도 무관한 파일은
  건드리지 않는다.
- 관리 화면(`http://127.0.0.1:8766/`)을 열어 두면 새로 남는 줄이 실시간으로
  붙는다.
- **토큰은 마스킹돼 남는다** (`al…(sha256:2bd806c9)` 형태 — 앞 두 글자 +
  SHA-256 앞 8자리). 다만 2글자 이하인 토큰은 이 규칙 때문에 사실상
  마스킹되지 않는다 — 앞 두 글자만 남기는데 토큰 전체가 두 글자뿐이면
  그대로 다 보인다는 뜻이다. 반면 **연결 ID(`instance=`)는 평문으로
  남는다.** 프로젝트 경로는 로그 파일에는 남지 않는다 — 관리 화면의 세션
  표와 `/api/status` 응답에만 나온다(위 경고 참고).
- 로그 디렉토리를 쓸 수 없으면(예: 부모 경로가 이미 파일인 경우) 파일
  로깅만 포기하고 서버는 정상적으로 뜬다.

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
- [ ] 서버를 띄우고 `~/.mcp-test-server/logs/`에 파일이 생기는지 본다
- [ ] 관리 화면을 열어 둔 채 다른 세션에서 도구를 부르면 로그가 실시간으로 붙는지 본다

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
