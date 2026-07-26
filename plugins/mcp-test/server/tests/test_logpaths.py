"""로그 경로 해석과 보관 청소."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mcp_test_server.logpaths import (
    DEFAULT_LOG_DIR,
    log_file_name,
    purge_logs,
    resolve_log_dir,
    tail_lines,
)

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def write_settings(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def settings_with(tmp_path: Path, log_dir: object) -> Path:
    return write_settings(
        tmp_path,
        {"pluginConfigs": {"mcp-test@basic-mcp-py-server": {"options": {"log_dir": log_dir}}}},
    )


# --- 우선순위 ---


def test_flag_wins_over_everything(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "/from/settings")
    chosen, warnings = resolve_log_dir(
        flag="/from/flag", env="/from/env", settings_path=settings
    )
    assert chosen == Path("/from/flag")
    assert warnings == []


def test_env_wins_over_settings(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "/from/settings")
    chosen, _ = resolve_log_dir(flag=None, env="/from/env", settings_path=settings)
    assert chosen == Path("/from/env")


def test_settings_wins_over_default(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "/from/settings")
    chosen, _ = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == Path("/from/settings")


def test_default_when_nothing_else(tmp_path: Path) -> None:
    chosen, warnings = resolve_log_dir(
        flag=None, env=None, settings_path=tmp_path / "absent.json"
    )
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []          # 파일이 없는 것은 정상이다


def test_tilde_and_relative_are_expanded(tmp_path: Path) -> None:
    chosen, _ = resolve_log_dir(flag="~/somewhere", env=None, settings_path=tmp_path / "x")
    assert chosen.is_absolute()
    assert "~" not in str(chosen)


# --- settings.json 실패 모드 (스펙 §4.3) ---


def test_broken_json_falls_back_and_warns(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=path)
    assert chosen == DEFAULT_LOG_DIR
    assert len(warnings) == 1


def test_missing_plugin_configs_key_is_silent(tmp_path: Path) -> None:
    settings = write_settings(tmp_path, {"model": "opus"})
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


def test_no_matching_plugin_id_is_silent(tmp_path: Path) -> None:
    settings = write_settings(
        tmp_path, {"pluginConfigs": {"other@market": {"options": {"log_dir": "/x"}}}}
    )
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


def test_matching_key_without_options_is_silent(tmp_path: Path) -> None:
    """설치했으나 이 항목만 미설정한 정상 상태다. 실패로 취급하지 않는다."""
    settings = write_settings(tmp_path, {"pluginConfigs": {"mcp-test@m": {"options": {}}}})
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


def test_two_matching_ids_picks_sorted_first_and_warns(tmp_path: Path) -> None:
    settings = write_settings(
        tmp_path,
        {
            "pluginConfigs": {
                "mcp-test@zzz": {"options": {"log_dir": "/from/zzz"}},
                "mcp-test@aaa": {"options": {"log_dir": "/from/aaa"}},
            }
        },
    )
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == Path("/from/aaa")
    assert len(warnings) == 1
    assert "mcp-test@aaa" in warnings[0]


def test_blank_log_dir_falls_back_and_warns(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, "   ")
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert len(warnings) == 1


def test_non_string_log_dir_falls_back_and_warns(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, 42)
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert len(warnings) == 1


def test_null_log_dir_is_silent(tmp_path: Path) -> None:
    settings = settings_with(tmp_path, None)
    chosen, warnings = resolve_log_dir(flag=None, env=None, settings_path=settings)
    assert chosen == DEFAULT_LOG_DIR
    assert warnings == []


# --- 파일명 ---


def test_log_file_name_carries_port_and_utc_date() -> None:
    assert log_file_name(8765, date(2026, 7, 25)) == "mcp-test-server.8765.2026-07-25.log"


# --- 보관 청소 ---


def aged(path: Path, now: datetime, hours: float) -> Path:
    path.write_text("x", encoding="utf-8")
    stamp = (now - timedelta(hours=hours)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_purge_deletes_only_files_older_than_72h(tmp_path: Path) -> None:
    old = aged(tmp_path / "mcp-test-server.8765.2026-07-22.log", NOW, 73)
    fresh = aged(tmp_path / "mcp-test-server.8765.2026-07-24.log", NOW, 24)

    removed, warnings = purge_logs(tmp_path, NOW)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
    assert warnings == []


def test_purge_ignores_files_that_are_not_ours(tmp_path: Path) -> None:
    """log_dir 은 사용자가 지정한다. 홈 디렉토리를 가리켜도 안전해야 한다."""
    stranger = aged(tmp_path / "taxes.pdf", NOW, 500)
    also = aged(tmp_path / "mcp-test-server.log", NOW, 500)   # 글롭에 맞지 않는다
    nested = tmp_path / "sub"
    nested.mkdir()
    deep = aged(nested / "mcp-test-server.1.2020-01-01.log", NOW, 500)  # 비재귀

    removed, _ = purge_logs(tmp_path, NOW)

    assert removed == 0
    assert stranger.exists()
    assert also.exists()
    assert deep.exists()


def test_purge_never_deletes_the_open_file(tmp_path: Path) -> None:
    current = aged(tmp_path / "mcp-test-server.8765.2026-07-20.log", NOW, 500)

    removed, _ = purge_logs(tmp_path, NOW, keep=current)

    assert removed == 0
    assert current.exists()


def test_purge_covers_other_ports(tmp_path: Path) -> None:
    aged(tmp_path / "mcp-test-server.9999.2026-07-01.log", NOW, 500)
    removed, _ = purge_logs(tmp_path, NOW)
    assert removed == 1


def test_purge_on_missing_directory_is_quiet(tmp_path: Path) -> None:
    removed, warnings = purge_logs(tmp_path / "absent", NOW)
    assert removed == 0
    assert warnings == []


# --- 꼬리 읽기 ---


def test_tail_returns_last_n_lines(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("\n".join(f"line{i}" for i in range(500)), encoding="utf-8")
    assert tail_lines(path, lines=3) == ["line497", "line498", "line499"]


def test_tail_drops_the_partial_first_line_when_truncated(tmp_path: Path) -> None:
    path = tmp_path / "b.log"
    path.write_text("A" * 100 + "\n" + "B" * 20 + "\n", encoding="utf-8")
    result = tail_lines(path, lines=10, max_bytes=50)
    assert result == ["B" * 20]      # 잘린 A 줄은 버린다


def test_tail_returns_nothing_when_the_last_line_exceeds_max_bytes(tmp_path: Path) -> None:
    """읽어 온 것이 전부 반쪽 줄이면 남길 온전한 줄이 없다.
    실제 로그 줄은 짧고 max_bytes 는 64KB 이므로 실무에서 걸리지 않는다."""
    path = tmp_path / "c.log"
    path.write_text("B" * 100, encoding="utf-8")
    assert tail_lines(path, lines=10, max_bytes=50) == []


def test_tail_on_missing_file_returns_empty(tmp_path: Path) -> None:
    assert tail_lines(tmp_path / "absent.log") == []


def test_tail_seeks_to_correct_byte_offset(tmp_path: Path) -> None:
    """seek 윈도우 계산이 정확한지 검증한다.

    고정폭 번호 줄로 오프셋을 손으로 계산 가능하게 만든다.
    파일: "0000\n0001\n...0049\n" = 50줄 × 5바이트 = 250바이트
    max_bytes: 60
    offset: 250 - 60 = 190 (줄38 중간)
    읽은 데이터: 줄38 일부 + "\n" + 줄39-49 (60바이트)
    partition("\n"): 첫 개행 앞을 버림 = 줄39-49만 남음
    따라서 11줄(줄39-49) 반환.
    오프셋이 12바이트 어긋나면 (190→202) 줄40부터 시작하므로 달라진다.
    """
    path = tmp_path / "d.log"
    lines = [f"{i:04d}\n" for i in range(50)]
    path.write_text("".join(lines), encoding="utf-8")
    # 파일 크기: 250바이트, max_bytes: 60
    # offset 250-60=190은 줄38 중간, partition 후 줄39-49만 남음
    result = tail_lines(path, lines=20, max_bytes=60)
    expected = [f"{i:04d}" for i in range(39, 50)]
    assert result == expected


def _aged_log(log_dir: Path, day_offset: int, hours_old: float, now: datetime) -> Path:
    """LOG_GLOB 에 맞는 파일 하나를 만들고 mtime 을 hours_old 만큼 되돌린다."""
    path = log_dir / log_file_name(8765, (now + timedelta(days=day_offset)).date())
    path.write_text("x\n", encoding="utf-8")
    stamp = (now - timedelta(hours=hours_old)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_one_day_retention_deletes_two_day_old_and_keeps_twelve_hour_old(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    old = _aged_log(tmp_path, -2, 48, now)
    fresh = _aged_log(tmp_path, 0, 12, now)

    removed, _ = purge_logs(tmp_path, now, max_age_seconds=1 * 86400)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_default_retention_is_still_seventy_two_hours(tmp_path: Path) -> None:
    # 회귀. 플래그를 주지 않은 경로가 예전과 같아야 한다.
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    inside = _aged_log(tmp_path, -2, 71, now)
    outside = _aged_log(tmp_path, -4, 73, now)

    removed, _ = purge_logs(tmp_path, now)

    assert removed == 1
    assert inside.exists()
    assert not outside.exists()
