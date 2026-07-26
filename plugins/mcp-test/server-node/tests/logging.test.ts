import { describe, expect, it, afterEach, vi } from 'vitest';
import { formatLine, getLogger, configureLogging, resetLogging } from '../src/logging.js';

const fixed = () => new Date('2026-07-26T01:35:36.789Z');

describe('formatLine', () => {
  it('밀리초를 버리고 레벨 5칸 카테고리 8칸으로 맞춘다', () => {
    // 파이썬 서버가 실제로 낸 줄과 바이트가 같아야 한다.
    expect(formatLine(fixed, 'WARN', 'http', 'POST /mcp 401 dur_ms=0 reason=blank-token'))
      .toBe('2026-07-26T01:35:36Z WARN  http     POST /mcp 401 dur_ms=0 reason=blank-token');
  });

  it('8칸을 넘는 카테고리는 자르지 않는다', () => {
    // 파이썬 쪽 streamable_http_manager 가 그렇다. 잘라내면 정보가 사라진다.
    expect(formatLine(fixed, 'INFO', 'verylongcategory', 'x'))
      .toBe('2026-07-26T01:35:36Z INFO  verylongcategory x');
  });
});

describe('getLogger', () => {
  afterEach(() => {
    resetLogging();
  });

  it('configureLogging() 이전에는 던지지 않는다', () => {
    // configureLogging() 을 부르지 않은 상태에서 로거를 사용해도 예외가 나지 않아야 한다.
    // getLogger 의 emit 에서 !currentClock 가드를 제거하면 formatLine(null, ...) 이 TypeError 를 던진다.
    const logger = getLogger('test');

    expect(() => {
      logger.info('message before config');
      logger.warn('another message');
      logger.error('error message');
    }).not.toThrow();
  });

  it('resetLogging() 후에는 sink 에 도착하지 않는다', () => {
    // resetLogging() 이 정말 sinks 배열을 비우는지 검증.
    const lines: string[] = [];
    const collectingSink = (line: string) => {
      lines.push(line);
    };

    // 처음에는 설정해서 로그가 나가는 것을 확인
    configureLogging({
      clock: fixed,
      sinks: [collectingSink],
    });

    const logger = getLogger('test');
    logger.info('message 1');

    // 첫 로그가 도착했는지 확인 — getLogger 의 emit 에서 sinks 루프를 제거하면 이 단언이 깨진다.
    expect(lines).toHaveLength(1);
    expect(lines[0]).toBe('2026-07-26T01:35:36Z INFO  test     message 1');

    // 설정을 리셋 — resetLogging() 에서 sinks = [] 를 제거하면 이 다음 단언이 깨진다.
    resetLogging();

    // 두 번째 로그는 도착하지 않음
    logger.info('message 2');
    expect(lines).toHaveLength(1); // 여전히 1개
  });

  it('sink 예외는 삼키되 나머지 sink 에는 계속 남긴다', () => {
    const lines: string[] = [];
    const throwingSink = () => {
      throw new Error('sink 실패');
    };
    const collectingSink = (line: string) => {
      lines.push(line);
    };

    // stderr 출력을 mock 해서 테스트 출력 깨끗하게 유지
    const stderrSpy = vi.spyOn(process.stderr, 'write').mockImplementation(() => true);

    try {
      configureLogging({
        clock: fixed,
        sinks: [throwingSink, collectingSink],
      });

      const logger = getLogger('test');

      // 첫 번째 sink 가 던져도 두 번째 sink 는 계속 받아야 한다.
      expect(() => {
        logger.info('message');
      }).not.toThrow();

      // 두 번째 sink 가 줄을 받았는지 확인 — getLogger 의 for 루프에서 try/catch 를 제거하면 던진다.
      expect(lines).toHaveLength(1);
      expect(lines[0]).toBe('2026-07-26T01:35:36Z INFO  test     message');

      // stderr 에 오류가 알려졌는지 확인 — catch 블록의 process.stderr.write() 를 제거하면 이 단언이 깨진다.
      expect(stderrSpy).toHaveBeenCalled();
      const callArgs = stderrSpy.mock.calls[0][0];
      expect(callArgs).toContain('[logging error]');
      expect(callArgs).toContain('sink 실패');
    } finally {
      stderrSpy.mockRestore();
    }
  });
});
