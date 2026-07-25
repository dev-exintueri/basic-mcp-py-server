"""세션 레지스트리. 이 프로세스의 유일한 상태 보유자다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionRecord:
    """하나의 Claude Code 연결. instance_id 하나에 레코드 하나가 대응한다."""

    instance_id: str
    subject: str
    project: str
    label: str
    mcp_session_id: str | None
    connected_at: datetime
    last_seen: datetime
    call_count: int
    blocked: bool


class Registry:
    """세션 레코드와 차단 상태를 들고 있는다.

    두 ASGI 앱이 같은 이벤트 루프에서 이 인스턴스 하나를 공유한다.
    별도의 락은 두지 않는데, 그것이 안전한 이유는 전제 하나에 달려 있다.

    **어떤 도구도 핸들러도 레지스트리를 읽은 뒤 고치기까지 사이에서
    await 해서는 안 된다.** 단일 이벤트 루프에서 중간에 양보하지 않는
    변경은 원자적이다. 양보하는 순간 원자적이지 않다 — 그 사이에 다른
    요청이 끼어들어 같은 레코드를 지우거나 바꿀 수 있다.

    아래 메서드는 전부 동기 함수다. 이 전제를 깨는 변경(예: 갱신 도중
    await 하는 비동기 메서드 추가)을 하려면 락부터 도입해야 한다.
    """

    def __init__(self, stale_after: float = 300.0, purge_after: float = 86400.0) -> None:
        self._records: dict[str, SessionRecord] = {}
        self.stale_after = stale_after
        self.purge_after = purge_after

    def touch(
        self,
        *,
        instance_id: str,
        subject: str,
        project: str,
        label: str,
        mcp_session_id: str | None,
        now: datetime,
    ) -> SessionRecord:
        """요청 하나를 반영한다. 없으면 만들고 있으면 갱신한다."""
        record = self._records.get(instance_id)
        if record is None:
            record = SessionRecord(
                instance_id=instance_id,
                subject=subject,
                project=project,
                label=label,
                mcp_session_id=mcp_session_id,
                connected_at=now,
                last_seen=now,
                call_count=1,
                blocked=False,
            )
            self._records[instance_id] = record
            return record

        record.last_seen = now
        record.call_count += 1
        record.subject = subject
        record.project = project
        record.label = label
        if mcp_session_id is not None:
            record.mcp_session_id = mcp_session_id
        return record

    def get(self, instance_id: str) -> SessionRecord | None:
        return self._records.get(instance_id)

    def all(self) -> list[SessionRecord]:
        return list(self._records.values())

    def remove(self, instance_id: str) -> bool:
        return self._records.pop(instance_id, None) is not None

    def block(self, instance_id: str) -> bool:
        record = self._records.get(instance_id)
        if record is None:
            return False
        record.blocked = True
        return True

    def unblock(self, instance_id: str) -> bool:
        record = self._records.get(instance_id)
        if record is None:
            return False
        record.blocked = False
        return True

    def is_blocked(self, instance_id: str) -> bool:
        record = self._records.get(instance_id)
        return record is not None and record.blocked

    def is_stale(self, record: SessionRecord, now: datetime) -> bool:
        return (now - record.last_seen).total_seconds() > self.stale_after

    def purge(self, now: datetime) -> int:
        """purge_after를 넘긴 레코드를 제거하고 제거한 개수를 반환한다."""
        doomed = [
            instance_id
            for instance_id, record in self._records.items()
            if (now - record.last_seen).total_seconds() > self.purge_after
        ]
        for instance_id in doomed:
            del self._records[instance_id]
        return len(doomed)


def session_view(
    record: SessionRecord, registry: Registry, now: datetime
) -> dict[str, object]:
    """세션 레코드를 JSON으로 옮길 수 있는 형태로 바꾼다.

    MCP 도구와 관리 앱이 같은 표현을 쓰도록 여기 한 곳에만 둔다.
    """
    return {
        "instance_id": record.instance_id,
        "subject": record.subject,
        "project": record.project,
        "label": record.label,
        "mcp_session_id": record.mcp_session_id,
        "connected_at": record.connected_at.isoformat(),
        "last_seen": record.last_seen.isoformat(),
        "call_count": record.call_count,
        "blocked": record.blocked,
        "stale": registry.is_stale(record, now),
    }
