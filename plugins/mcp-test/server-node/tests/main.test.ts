import { describe, expect, it } from 'vitest';
import { parseArgs } from '../src/main.js';

describe('parseArgs', () => {
  // 파이썬 __main__.py 의 argparse 를 실제로 돌려서 확인한 경계다:
  //
  //   uv run --directory plugins/mcp-test/server python -c "
  //   from mcp_test_server.__main__ import parse_args
  //   parse_args(['--port', '8765.5'])  # SystemExit(2): invalid int value
  //   parse_args(['--port', '-1'])      # 통과: Namespace(port=-1, ...)
  //   parse_args(['--stale-after', '8765.5'])  # 통과: 8765.5
  //   "
  //
  // --port/--admin-port 는 argparse type=int 라 소수점이 있으면 거부하지만
  // 음수·0 은 받는다(그 값은 listen() 이 나중에 거부한다). --stale-after 는
  // type=float 라 숫자로 못 읽을 때만 거부한다.

  it('--port 가 정수가 아니면 거부한다 (파이썬 argparse: invalid int value)', () => {
    expect(() => parseArgs(['--port', 'abc'])).toThrow();
    expect(() => parseArgs(['--port', '8765.5'])).toThrow();
  });

  it('--port 의 음수·0 은 그대로 받는다 (파이썬 argparse 도 받는다)', () => {
    // node:util 의 parseArgs() 는 `--port -1` (공백으로 분리) 을 다른
    // 옵션과 헷갈릴 수 있는 값으로 보고 그 자체를 거부한다(우리 코드 밖의
    // 별개 제약). `--port=-1` 형태로 넘기면 피할 수 있다 — 파이썬
    // argparse 는 이 문제가 없으므로 실제 CLI 사용성 차이가 있지만, 이번
    // 라운드가 다루는 "타입 검증" 범위 밖이라 Task 9 로 넘긴다.
    expect(parseArgs(['--port=-1']).port).toBe(-1);
    expect(parseArgs(['--port', '0']).port).toBe(0);
  });

  it('--admin-port 가 정수가 아니면 거부한다', () => {
    expect(() => parseArgs(['--admin-port', 'abc'])).toThrow();
  });

  it('--stale-after 가 숫자가 아니면 거부한다', () => {
    expect(() => parseArgs(['--stale-after', 'abc'])).toThrow();
  });

  it('--stale-after 는 소수·음수·0 을 그대로 받는다 (파이썬 type=float 와 동일)', () => {
    expect(parseArgs(['--stale-after', '8765.5']).staleAfter).toBe(8765.5);
    // 음수는 --stale-after=-1 형태로 넘긴다. 이유는 위 --port 테스트의
    // 주석과 같다 (node:util parseArgs 의 별개 제약).
    expect(parseArgs(['--stale-after=-1']).staleAfter).toBe(-1);
    expect(parseArgs(['--stale-after', '0']).staleAfter).toBe(0);
  });
});
