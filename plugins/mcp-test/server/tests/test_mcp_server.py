import os
from datetime import datetime, timedelta, timezone

from mcp_test_server.mcp_server import build_mcp
from mcp_test_server.registry import Registry

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def make_registry():
    registry = Registry(stale_after=300.0)
    registry.touch(
        instance_id="abc123",
        subject="alice",
        project="/tmp/proj",
        label="left",
        mcp_session_id=None,
        now=T0,
    )
    return registry


async def test_server_exposes_exactly_four_tools():
    mcp = build_mcp(make_registry(), started_at=T0, clock=lambda: T0)
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == {"ping", "echo", "whoami", "sessions"}


async def test_echo_returns_the_same_text():
    mcp = build_mcp(make_registry(), started_at=T0, clock=lambda: T0)
    result = await mcp.call_tool("echo", {"text": "안녕"})
    assert "안녕" in str(result)


async def test_ping_reports_this_process_pid():
    mcp = build_mcp(
        make_registry(), started_at=T0, clock=lambda: T0 + timedelta(seconds=42)
    )
    result = await mcp.call_tool("ping", {})
    assert str(os.getpid()) in str(result)


async def test_tool_call_is_logged_with_name_and_instance(caplog) -> None:
    import logging

    from mcp_test_server.registry import Registry

    caplog.set_level(logging.INFO, logger="mcp_test_server.call")
    registry = Registry(stale_after=300.0)
    mcp = build_mcp(registry, started_at=T0, clock=lambda: T0)

    await mcp.call_tool("echo", {"text": "안녕"})

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp_test_server.call"]
    assert len(lines) == 1
    assert "tool=echo" in lines[0]
    assert "dur_ms=" in lines[0]
    assert "ok" in lines[0]


async def test_tool_call_success_is_logged_as_info(caplog) -> None:
    """성공한 도구 호출이 INFO로 기록된다."""
    import logging

    from mcp_test_server.registry import Registry

    caplog.set_level(logging.INFO, logger="mcp_test_server.call")
    registry = Registry(stale_after=300.0)
    mcp = build_mcp(registry, started_at=T0, clock=lambda: T0)

    result = await mcp.call_tool("echo", {"text": "test"})
    assert "test" in str(result)

    records = [r for r in caplog.records if r.name == "mcp_test_server.call"]
    assert records and records[0].levelno == logging.INFO
    assert "ok" in records[0].getMessage()


def test_tool_failure_is_logged_as_warning(caplog) -> None:
    """데코레이터의 except 분기를 직접 테스트한다.

    brief의 원본은 FastMCP 인자 검증 오류를 로깅하려 했는데, 이는 불가능하다:
    검증 실패 시 데코레이터 래퍼가 호출되기 전에 FastMCP가 예외를 발생시킨다.
    대신 데코레이터 자체를 단위 테스트한다.
    """
    import logging

    import pytest

    from mcp_test_server.mcp_server import _logged

    caplog.set_level(logging.INFO, logger="mcp_test_server.call")

    # 의도적으로 실패하는 함수
    def failing_tool():
        raise ValueError("test error")

    # 데코레이터 적용
    decorated = _logged(failing_tool)

    # 예외가 전파되는지 확인
    with pytest.raises(ValueError):
        decorated()

    # 정확히 하나의 WARNING 레코드가 생성되었는지 확인
    records = [r for r in caplog.records if r.name == "mcp_test_server.call"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    msg = records[0].getMessage()
    assert "error=ValueError" in msg
    assert "dur_ms=" in msg
    assert "tool=failing_tool" in msg


async def test_tool_schemas_are_unchanged_by_the_logging_decorator() -> None:
    """데코레이터가 시그니처를 가리면 도구가 조용히 망가진다."""
    from mcp_test_server.registry import Registry

    mcp = build_mcp(Registry(stale_after=300.0), started_at=T0, clock=lambda: T0)
    by_name = {t.name: t for t in await mcp.list_tools()}

    assert set(by_name) == {"ping", "echo", "whoami", "sessions"}
    assert sorted(by_name["echo"].inputSchema.get("properties", {})) == ["text"]
    assert by_name["echo"].inputSchema.get("required") == ["text"]
    assert by_name["ping"].inputSchema.get("properties", {}) == {}
    assert by_name["whoami"].inputSchema.get("properties", {}) == {}
