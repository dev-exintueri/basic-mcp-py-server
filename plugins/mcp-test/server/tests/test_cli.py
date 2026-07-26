"""CLI 인자 파싱과 그 값이 serve() 까지 도달하는지 검사한다."""

from __future__ import annotations

import pytest

from mcp_test_server.__main__ import main, parse_args


def test_log_retention_days_defaults_to_three():
    assert parse_args([]).log_retention_days == 3


def test_log_retention_days_accepts_a_positive_integer():
    assert parse_args(["--log-retention-days", "7"]).log_retention_days == 7


@pytest.mark.parametrize("value", ["0", "-1"])
def test_log_retention_days_rejects_zero_and_negative(value, capsys):
    # 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
    with pytest.raises(SystemExit) as exc:
        parse_args(["--log-retention-days", value])
    assert exc.value.code == 2
    # 종료 코드만 보면 안 된다. 인자가 아예 없을 때 argparse 가 내는
    # "unrecognized arguments" 도 코드 2라서, 검증이 통째로 빠져도 통과한다.
    assert "1 이상" in capsys.readouterr().err


def test_main_converts_retention_days_to_seconds(monkeypatch, tmp_path):
    """일수를 초로 바꿔 serve() 까지 넘기는지 본다.

    이 테스트가 없으면 배선이 통째로 끊겨도 아무도 모른다. purge_logs 를
    직접 부르는 테스트는 `max_age_seconds` 키워드가 이미 있으므로 CLI 가
    값을 전혀 넘기지 않아도 통과한다.

    main() 은 전역 로깅을 건드리고 끝에 logging.shutdown() 을 부른다.
    그대로 두면 pytest 의 로그 캡처 핸들러까지 닫혀 이후 테스트가
    오염되므로, 이 테스트가 보려는 배선만 남기고 나머지는 막는다.
    """
    captured: dict[str, object] = {}

    async def fake_serve(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("mcp_test_server.__main__.serve", fake_serve)
    monkeypatch.setattr("mcp_test_server.__main__.configure_logging", lambda **kw: None)
    monkeypatch.setattr("mcp_test_server.__main__.logging.shutdown", lambda: None)

    assert main(["--log-retention-days", "5", "--log-dir", str(tmp_path)]) == 0
    assert captured["log_max_age_seconds"] == 5 * 86400
