/**
 * 세션 레지스트리. 이 프로세스의 유일한 상태 보유자다.
 *
 * 노드는 단일 스레드이고 아래 메서드는 전부 동기 함수이므로 락이 없다.
 * 파이썬 쪽과 같은 전제다 — 레코드를 읽은 뒤 고치기까지 사이에서 await
 * 하지 않는다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** SessionRecord 의 필드와 sessionView() 의 출력이
 * 이 서버가 세션에 대해 무엇을 아는지 정한다.
 *
 * **함께 바꿔야 하는 것.** 필드를 늘리면 두 곳이 따라온다 — 값을 어디서
 * 얻는가(auth 의 Identity 와 touch() 호출), 화면에 어떻게 보이는가
 * (admin 의 행 템플릿과 열 제목). 그리고 conformance 스위트가
 * sessionView 의 키 집합을 단언한다.
 *
 * **깨면 안 되는 것.** 갱신 도중 await 하는 비동기 메서드를 더하지 않는다.
 */

export interface SessionRecord {
  instanceId: string;
  subject: string;
  project: string;
  label: string;
  mcpSessionId: string | null;
  connectedAt: Date;
  lastSeen: Date;
  callCount: number;
  blocked: boolean;
}

export interface TouchInput {
  instanceId: string;
  subject: string;
  project: string;
  label: string;
  mcpSessionId: string | null;
  now: Date;
}

export class Registry {
  private records = new Map<string, SessionRecord>();

  constructor(
    public staleAfter = 300.0,
    public purgeAfter = 86400.0,
  ) {}

  touch(input: TouchInput): SessionRecord {
    const existing = this.records.get(input.instanceId);
    if (existing === undefined) {
      const record: SessionRecord = {
        instanceId: input.instanceId,
        subject: input.subject,
        project: input.project,
        label: input.label,
        mcpSessionId: input.mcpSessionId,
        connectedAt: input.now,
        lastSeen: input.now,
        callCount: 1,
        blocked: false,
      };
      this.records.set(input.instanceId, record);
      return record;
    }
    existing.lastSeen = input.now;
    existing.callCount += 1;
    existing.subject = input.subject;
    existing.project = input.project;
    existing.label = input.label;
    if (input.mcpSessionId !== null) existing.mcpSessionId = input.mcpSessionId;
    return existing;
  }

  get(instanceId: string): SessionRecord | undefined {
    return this.records.get(instanceId);
  }

  all(): SessionRecord[] {
    return [...this.records.values()];
  }

  remove(instanceId: string): boolean {
    return this.records.delete(instanceId);
  }

  block(instanceId: string): boolean {
    const record = this.records.get(instanceId);
    if (record === undefined) return false;
    record.blocked = true;
    return true;
  }

  unblock(instanceId: string): boolean {
    const record = this.records.get(instanceId);
    if (record === undefined) return false;
    record.blocked = false;
    return true;
  }

  isBlocked(instanceId: string): boolean {
    return this.records.get(instanceId)?.blocked ?? false;
  }

  isStale(record: SessionRecord, now: Date): boolean {
    return (now.getTime() - record.lastSeen.getTime()) / 1000 > this.staleAfter;
  }

  purge(now: Date): number {
    const doomed = this.all().filter(
      (r) => (now.getTime() - r.lastSeen.getTime()) / 1000 > this.purgeAfter,
    );
    for (const record of doomed) this.records.delete(record.instanceId);
    return doomed.length;
  }
}

/**
 * 세션 레코드를 JSON 으로 옮길 수 있는 형태로 바꾼다.
 *
 * MCP 도구와 관리 앱이 같은 표현을 쓰도록 여기 한 곳에만 둔다. 키 이름은
 * 파이썬 쪽 session_view() 와 같은 snake_case 다 — 이것이 계약이다.
 */
export function sessionView(
  record: SessionRecord,
  registry: Registry,
  now: Date,
): Record<string, unknown> {
  return {
    instance_id: record.instanceId,
    subject: record.subject,
    project: record.project,
    label: record.label,
    mcp_session_id: record.mcpSessionId,
    connected_at: record.connectedAt.toISOString(),
    last_seen: record.lastSeen.toISOString(),
    call_count: record.callCount,
    blocked: record.blocked,
    stale: registry.isStale(record, now),
  };
}
