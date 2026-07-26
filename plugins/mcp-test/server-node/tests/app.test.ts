import { describe, expect, it } from 'vitest';
import { isLoopback } from '../src/app.js';

describe('isLoopback', () => {
  // 파이썬 mcp_test_server.app.is_loopback() 을 실제로 돌려서 받은 표다:
  //
  //   uv run --directory plugins/mcp-test/server python -c "
  //   from mcp_test_server.app import is_loopback
  //   for h in ['127.0.0.1','127.0.0.2','127.255.255.254','::1','localhost',
  //             'LOCALHOST','0.0.0.0','::','192.168.1.5','::ffff:127.0.0.1',
  //             'not-a-host']:
  //       print(repr(h), is_loopback(h))
  //   "
  //
  // 이 표는 파이썬 tests/test_app.py 의 파라미터라이즈 표와 짝이다. 둘 중
  // 하나만 바뀌면 "밖에서 구별되지 않는다"는 계약이 깨진다.
  it.each([
    ['127.0.0.1', true],
    ['127.0.0.2', true],
    ['127.255.255.254', true],
    ['::1', true],
    ['localhost', true],
    ['LOCALHOST', true],
    ['0.0.0.0', false],
    ['::', false],
    ['192.168.1.5', false],
    ['::ffff:127.0.0.1', true],
    ['not-a-host', false],
  ] as const)('%s -> %s (파이썬과 동일)', (host, expected) => {
    expect(isLoopback(host)).toBe(expected);
  });
});
