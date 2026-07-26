import { describe, expect, it, afterEach } from 'vitest';
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

  it('configureLogging() 이전에는 아무 데도 나가지 않는다', () => {
    // configureLogging() 을 부르지 않은 상태에서 로그 호출은 throw 하지 않고 아무 곳에도 나가지 않는다.
    const lines: string[] = [];
    const collectingSink = (line: string) => {
      lines.push(line);
    };

    // 설정을 하지 않은 상태에서 로거 생성
    const logger = getLogger('test');

    // 로그를 호출해도 오류가 나지 않아야 한다. configureLogging() 을 부르지 않았으므로 아무것도 나가지 않는다.
    expect(() => {
      logger.info('message before config');
      logger.warn('another message');
      logger.error('error message');
    }).not.toThrow();

    // sink 를 등록하지 않았으므로 lines 배열은 비어 있다.
    expect(lines).toHaveLength(0);
  });

  it('sink 예외는 삼키되 나머지 sink 에는 계속 남긴다', () => {
    const lines: string[] = [];
    const throwingSink = () => {
      throw new Error('sink 실패');
    };
    const collectingSink = (line: string) => {
      lines.push(line);
    };

    configureLogging({
      clock: fixed,
      sinks: [throwingSink, collectingSink],
    });

    const logger = getLogger('test');

    // 첫 번째 sink 가 던져도 두 번째 sink 는 계속 받아야 한다.
    expect(() => {
      logger.info('message');
    }).not.toThrow();

    // 두 번째 sink 가 줄을 받았는지 확인
    expect(lines).toHaveLength(1);
    expect(lines[0]).toBe('2026-07-26T01:35:36Z INFO  test     message');
  });
});
