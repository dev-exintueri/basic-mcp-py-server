# 로그 보관 기간을 CLI 플래그로 받는다

**목표:** 하드코딩된 72시간 보관을 `--log-retention-days` 로 설정 가능하게 한다.

**배경:** 이 변경은 `basic-channel-py-server` 와의 로깅·어드민 체계 대조에서 나왔다. 그 대조에서 **MCP 가 채널을 따라가는 유일한 항목**이 이것이다. 나머지 방향(접근 로그, 로그 줄 위조 차단, 크래시 경로, 열린 파일 보호, status 필드)은 전부 채널 쪽이 MCP 를 따라간다.

전체 대조 결과는 이웃 저장소에 있다.

```
~/workspace/dev-exintueri/basic-channel-py-server
  .claude/worktrees/channel-test-app/docs/superpowers/specs/
    2026-07-26-logging-admin-alignment-design.md      ← §8 이 이 문서의 원본
```

브랜치 `feat/channel-test-app` 에 있고 아직 `main` 에 병합되지 않았다.

---

## 결정

`logpaths.MAX_AGE_SECONDS = 259200.0` 은 기본값으로 남긴다. CLI 가 값을 덮어쓴다.

| 항목 | 값 |
|---|---|
| 플래그 | `--log-retention-days` |
| 타입 | `int` |
| 기본값 | `3` |
| 검증 | `0` 이하 거부. 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다 |

`purge_logs` 는 이미 `max_age_seconds` 를 키워드 인자로 받으므로(`logpaths.py:104`) **시그니처 변경이 없다.** 값을 거기까지 흘려보내기만 하면 된다.

## 배선 경로

| 파일 | 변경 |
|---|---|
| `__main__.py` | 인자 추가 → 검증 → `serve()` 로 전달 |
| `app.py:204` | `_purge_loop(...)` 가 `max_age_seconds` 를 받는다 |
| `app.py:302` | 기동 직후 1회 purge 에 전달 |
| `app.py:310` | `_purge_loop` 태스크 생성 시 전달 |
| `README.md` | "보관 기간은 72시간이고" 를 기본값 표기로 고친다 |

## 테스트

- `--log-retention-days 0` 과 음수가 종료 코드 2로 거부되는지
- 값이 `purge_logs(max_age_seconds=...)` 까지 도달하는지 — 하루짜리 보관에서 이틀 된 파일이 지워지고 12시간 된 파일이 남는지
- 플래그를 주지 않으면 기존 72시간 동작이 그대로인지 (회귀)
