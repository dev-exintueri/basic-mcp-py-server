from datetime import datetime, timedelta, timezone

import pytest

from mcp_test_server.registry import Registry, SessionRecord, session_view

T0 = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def touch(reg, instance_id="abc123", now=T0, **kwargs):
    defaults = dict(
        subject="alice",
        project="/tmp/proj",
        label="unnamed",
        mcp_session_id=None,
    )
    defaults.update(kwargs)
    return reg.touch(instance_id=instance_id, now=now, **defaults)


def test_touch_creates_record():
    reg = Registry()
    rec = touch(reg)
    assert isinstance(rec, SessionRecord)
    assert rec.instance_id == "abc123"
    assert rec.subject == "alice"
    assert rec.connected_at == T0
    assert rec.last_seen == T0
    assert rec.call_count == 1
    assert rec.blocked is False


def test_touch_twice_updates_last_seen_and_count():
    reg = Registry()
    touch(reg)
    later = T0 + timedelta(seconds=30)
    rec = touch(reg, now=later)
    assert rec.connected_at == T0
    assert rec.last_seen == later
    assert rec.call_count == 2
    assert len(reg.all()) == 1


def test_touch_records_mcp_session_id_when_present():
    reg = Registry()
    rec = touch(reg, mcp_session_id="legacy-sid")
    assert rec.mcp_session_id == "legacy-sid"


def test_distinct_instances_are_separate_records():
    reg = Registry()
    touch(reg, instance_id="one")
    touch(reg, instance_id="two")
    assert {r.instance_id for r in reg.all()} == {"one", "two"}


def test_get_and_remove():
    reg = Registry()
    touch(reg)
    assert reg.get("abc123") is not None
    assert reg.remove("abc123") is True
    assert reg.get("abc123") is None
    assert reg.remove("abc123") is False


def test_block_and_unblock():
    reg = Registry()
    touch(reg)
    assert reg.is_blocked("abc123") is False
    assert reg.block("abc123") is True
    assert reg.is_blocked("abc123") is True
    assert reg.get("abc123").blocked is True
    assert reg.unblock("abc123") is True
    assert reg.is_blocked("abc123") is False


def test_block_unknown_instance_returns_false():
    reg = Registry()
    assert reg.block("nope") is False
    assert reg.unblock("nope") is False


def test_is_stale_uses_stale_after():
    reg = Registry(stale_after=300.0)
    rec = touch(reg)
    assert reg.is_stale(rec, T0 + timedelta(seconds=299)) is False
    assert reg.is_stale(rec, T0 + timedelta(seconds=301)) is True


def test_purge_removes_only_records_past_purge_after():
    reg = Registry(stale_after=300.0, purge_after=86400.0)
    touch(reg, instance_id="old")
    touch(reg, instance_id="fresh", now=T0 + timedelta(hours=23))
    removed = reg.purge(T0 + timedelta(hours=24, seconds=1))
    assert removed == 1
    assert {r.instance_id for r in reg.all()} == {"fresh"}


def test_session_view_serialises_a_record():
    reg = Registry(stale_after=300.0)
    view = session_view(touch(reg), reg, now=T0)
    assert view["instance_id"] == "abc123"
    assert view["subject"] == "alice"
    assert view["project"] == "/tmp/proj"
    assert view["label"] == "unnamed"
    assert view["mcp_session_id"] is None
    assert view["call_count"] == 1
    assert view["blocked"] is False
    assert view["stale"] is False
    assert view["connected_at"] == T0.isoformat()
    assert view["last_seen"] == T0.isoformat()


def test_session_view_marks_stale_records():
    reg = Registry(stale_after=300.0)
    record = touch(reg)
    assert session_view(record, reg, now=T0 + timedelta(seconds=301))["stale"] is True
