import { describe, expect, it } from 'vitest';
import { formatLine } from '../src/logging.js';

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
