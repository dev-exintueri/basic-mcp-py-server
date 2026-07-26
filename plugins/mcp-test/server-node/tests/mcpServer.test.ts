import { afterEach, describe, expect, it } from 'vitest';
import { logged } from '../src/mcpServer.js';
import { configureLogging, resetLogging } from '../src/logging.js';

// logging.test.ts 와 같은 패턴: 고정 시계 + 수집용 sink.
const fixed = () => new Date('2026-07-26T01:35:36.789Z');

function withCollector(): string[] {
  const lines: string[] = [];
  configureLogging({ clock: fixed, sinks: [(line) => lines.push(line)] });
  return lines;
}

describe('logged', () => {
  afterEach(() => {
    // 전역 상태다. 다음 테스트 파일에 새는 것을 막는다.
    resetLogging();
  });

  it('성공하면 결과를 그대로 돌려주고 tool=<name> instance=<id> dur_ms=<n> ok 를 남긴다', () => {
    const lines = withCollector();
    const extra = { requestInfo: { headers: { 'x-client-instance': 'abc123' } } };

    const result = logged('ping', extra, () => 'result-value');

    // logged() 의 `return result;` 를 지우면 이 값이 undefined 가 되어 깨진다.
    expect(result).toBe('result-value');
    expect(lines).toHaveLength(1);
    // call 카테고리로, INFO 레벨로, ok 로 끝난다 — dur_ms 의 숫자는 실행 시간에
    // 따라 달라지므로 자릿수만 본다.
    expect(lines[0]).toMatch(/INFO\s+call\s+tool=ping instance=abc123 dur_ms=\d+ ok$/);
  });

  it('extra 나 헤더가 없으면 instance=unknown 으로 남긴다', () => {
    const lines = withCollector();

    logged('sessions', undefined, () => 'x');

    // instanceIdOf() 의 `?? UNKNOWN_INSTANCE`(||) 대체를 지우면 instance= 뒤가
    // 비거나 undefined 로 남아 이 단언이 깨진다.
    expect(lines[0]).toContain('instance=unknown');
  });

  it('던지면 그대로 다시 던지고 WARN 에 error=<생성자 이름> 을 남긴다', () => {
    const lines = withCollector();
    const extra = { requestInfo: { headers: { 'x-client-instance': 'abc123' } } };

    expect(() =>
      logged('boom', extra, () => {
        throw new TypeError('test error');
      }),
    ).toThrow(TypeError);

    // catch 블록의 `throw error;` 를 지우면 위 toThrow() 단언이 먼저 깨진다.
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatch(/WARN/);
    expect(lines[0]).toContain('tool=boom');
    expect(lines[0]).toContain('instance=abc123');
    // catch 블록의 logger.warn(...) 호출을 지우면 이 세 단언이 깨진다 —
    // 실제로 지워서 확인했다(리포트 참고).
    expect(lines[0]).toContain('error=TypeError');
    expect(lines[0]).toMatch(/dur_ms=\d+/);
  });
});
