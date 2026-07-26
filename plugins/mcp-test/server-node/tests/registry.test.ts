import { describe, expect, it } from 'vitest';
import { Registry, sessionView, type TouchInput } from '../src/registry.js';

// 파이썬 tests/test_registry.py 를 옮긴다. 기계적으로 베끼지 않고, 각
// 단언을 노드 Registry 에 실제로 돌려서 확인한 뒤 남겼다 — touch() 의
// mcpSessionId 갱신 규칙(input.mcpSessionId !== null 일 때만 덮어쓴다)이
// 파이썬과 동일함을 포함해서다.

const T0 = new Date('2026-07-25T12:00:00Z');

function touch(
  registry: Registry,
  overrides: Partial<TouchInput> & { instanceId?: string; now?: Date } = {},
) {
  const input: TouchInput = {
    instanceId: 'abc123',
    subject: 'alice',
    project: '/tmp/proj',
    label: 'unnamed',
    mcpSessionId: null,
    now: T0,
    ...overrides,
  };
  return registry.touch(input);
}

describe('Registry', () => {
  it('touch() 는 새 레코드를 만든다', () => {
    const registry = new Registry();
    const record = touch(registry);

    expect(record.instanceId).toBe('abc123');
    expect(record.subject).toBe('alice');
    expect(record.connectedAt).toEqual(T0);
    expect(record.lastSeen).toEqual(T0);
    expect(record.callCount).toBe(1);
    expect(record.blocked).toBe(false);
  });

  it('touch() 를 두 번 부르면 lastSeen 과 callCount 만 갱신되고 connectedAt 은 그대로다', () => {
    // registry.ts 의 touch() 에서 `existing.connectedAt = ...` 을 실수로
    // 더하면 이 단언이 잡는다.
    const registry = new Registry();
    touch(registry);
    const later = new Date(T0.getTime() + 30_000);
    const record = touch(registry, { now: later });

    expect(record.connectedAt).toEqual(T0);
    expect(record.lastSeen).toEqual(later);
    expect(record.callCount).toBe(2);
    expect(registry.all()).toHaveLength(1);
  });

  it('mcpSessionId 가 있으면 기록한다', () => {
    const registry = new Registry();
    const record = touch(registry, { mcpSessionId: 'legacy-sid' });
    expect(record.mcpSessionId).toBe('legacy-sid');
  });

  it('기존 레코드에 mcpSessionId: null 로 다시 touch() 해도 이전 값을 지우지 않는다', () => {
    // registry.ts 의 `if (input.mcpSessionId !== null) existing.mcpSessionId = ...`
    // 가드를 지우면(무조건 덮어쓰면) 이 단언이 깨진다 — 파이썬 registry.py
    // 의 같은 가드와 동작을 맞추는 지점이다.
    const registry = new Registry();
    touch(registry, { mcpSessionId: 'legacy-sid' });
    const record = touch(registry, { mcpSessionId: null, now: new Date(T0.getTime() + 1000) });
    expect(record.mcpSessionId).toBe('legacy-sid');
  });

  it('인스턴스가 다르면 레코드도 분리된다', () => {
    const registry = new Registry();
    touch(registry, { instanceId: 'one' });
    touch(registry, { instanceId: 'two' });
    expect(new Set(registry.all().map((r) => r.instanceId))).toEqual(new Set(['one', 'two']));
  });

  it('get() 과 remove()', () => {
    const registry = new Registry();
    touch(registry);
    expect(registry.get('abc123')).not.toBeUndefined();
    expect(registry.remove('abc123')).toBe(true);
    expect(registry.get('abc123')).toBeUndefined();
    expect(registry.remove('abc123')).toBe(false);
  });

  it('block() 과 unblock()', () => {
    const registry = new Registry();
    touch(registry);
    expect(registry.isBlocked('abc123')).toBe(false);
    expect(registry.block('abc123')).toBe(true);
    expect(registry.isBlocked('abc123')).toBe(true);
    expect(registry.get('abc123')?.blocked).toBe(true);
    expect(registry.unblock('abc123')).toBe(true);
    expect(registry.isBlocked('abc123')).toBe(false);
  });

  it('모르는 인스턴스에 block()/unblock() 은 false 를 돌려준다', () => {
    const registry = new Registry();
    expect(registry.block('nope')).toBe(false);
    expect(registry.unblock('nope')).toBe(false);
  });

  it('isStale() 은 staleAfter 를 쓴다', () => {
    // registry.ts 의 isStale() 을 상수 false 로 바꾸면(리뷰 실측 변이)
    // 이 두 단언이 모두 실패하지 않고 두 번째만 실패해야 하는데, 상수
    // false 로 바꾸면 두 번째가 깨진다.
    const registry = new Registry(300.0);
    const record = touch(registry);
    expect(registry.isStale(record, new Date(T0.getTime() + 299_000))).toBe(false);
    expect(registry.isStale(record, new Date(T0.getTime() + 301_000))).toBe(true);
  });

  it('purge() 는 purgeAfter 를 넘긴 레코드만 지운다', () => {
    // registry.ts 의 purge() 를 무동작으로 바꾸면(리뷰 실측 변이) removed
    // 가 0 이 되고 'old' 가 살아남아 이 단언이 깨진다.
    const registry = new Registry(300.0, 86400.0);
    touch(registry, { instanceId: 'old' });
    touch(registry, { instanceId: 'fresh', now: new Date(T0.getTime() + 23 * 3600 * 1000) });

    const removed = registry.purge(new Date(T0.getTime() + (24 * 3600 + 1) * 1000));

    expect(removed).toBe(1);
    expect(registry.all().map((r) => r.instanceId)).toEqual(['fresh']);
  });

  it('sessionView() 는 레코드를 JSON 가능한 형태로 바꾼다', () => {
    const registry = new Registry(300.0);
    const view = sessionView(touch(registry), registry, T0);

    expect(view.instance_id).toBe('abc123');
    expect(view.subject).toBe('alice');
    expect(view.project).toBe('/tmp/proj');
    expect(view.label).toBe('unnamed');
    expect(view.mcp_session_id).toBeNull();
    expect(view.call_count).toBe(1);
    expect(view.blocked).toBe(false);
    expect(view.stale).toBe(false);
    expect(view.connected_at).toBe(T0.toISOString());
    expect(view.last_seen).toBe(T0.toISOString());
  });

  it('sessionView() 는 stale 레코드를 표시한다', () => {
    const registry = new Registry(300.0);
    const record = touch(registry);
    const view = sessionView(record, registry, new Date(T0.getTime() + 301_000));
    expect(view.stale).toBe(true);
  });
});
