"""CLI 플래그의 계약. 서버가 뜨기 전에 끝나는 것들이다."""

from __future__ import annotations

import pytest

from conftest import free_port


def test_zero_retention_is_rejected(spawn, tmp_path) -> None:
    # 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
    #
    # --log-dir 와 --port/--admin-port 를 반드시 준다. 거부가 회귀하면(즉
    # 이 값이 통과해 버리면) 서버가 실제로 뜬다 — 그때 이 인자들이 없으면
    # 기본 포트 8765/8766 과 사용자의 실제 ~/.mcp-test-server/logs 를
    # 건드린다(M-16, 최종 리뷰).
    port, admin_port = free_port(), free_port()
    proc, output = spawn(
        [
            "--log-retention-days", "0",
            "--port", str(port),
            "--admin-port", str(admin_port),
            "--log-dir", str(tmp_path),
        ]
    )
    assert proc.returncode not in (None, 0), output


def test_negative_retention_is_rejected(spawn, tmp_path) -> None:
    # 실측(Task 9): 두 런타임 모두 종료 코드 2로 거부하지만 이유는 다르다.
    # node:util.parseArgs 는 공백으로 구분된 음수를 "ambiguous"(다음 토큰이
    # 값인지 새 플래그인지 모호하다)로 보고 그 자체를 거부하는 반면, 파이썬
    # argparse 는 값으로 받아들인 뒤 우리 검증(log_retention_days <= 0)이
    # 거부한다. 이유가 다르므로 정확한 종료 코드값을 계약하지 않고, "0도
    # None도 아니다"만 두 런타임이 합의하는 수준으로 본다.
    #
    # --log-dir 와 --port/--admin-port 이유는 위 test_zero_retention_is_rejected 참고.
    port, admin_port = free_port(), free_port()
    proc, output = spawn(
        [
            "--log-retention-days", "-1",
            "--port", str(port),
            "--admin-port", str(admin_port),
            "--log-dir", str(tmp_path),
        ]
    )
    assert proc.returncode not in (None, 0), output


def test_empty_numeric_flag_is_rejected(spawn, tmp_path) -> None:
    """빈 문자열은 숫자가 아니다.

    실측(Task 9): 노드는 Number('') === 0 이라 requireInt() 를 조용히
    통과해 포트 0(임의 포트)으로 뜬다. 파이썬 argparse 는 int('') 에서
    ValueError 를 내고 exit 2로 거부한다. main.ts 의 requireInt()에 공백
    가드를 추가해 두 런타임을 맞춘다.

    --port 를 빈 문자열로 덮어써서 거부를 겨냥하는 테스트이므로 --port 는
    줄 수 없다 — 그게 이 테스트의 핵심이다. 대신 --admin-port 와
    --log-dir 를 줘서, 거부가 회귀했을 때(포트 0 으로 조용히 떴을 때)라도
    관리 리스너와 로그만큼은 기본값(8766, ~/.mcp-test-server/logs)을
    건드리지 않게 한다.
    """
    admin_port = free_port()
    proc, output = spawn(
        ["--port", "", "--admin-port", str(admin_port), "--log-dir", str(tmp_path)]
    )
    assert proc.returncode not in (None, 0), output


@pytest.mark.exposes_port
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
