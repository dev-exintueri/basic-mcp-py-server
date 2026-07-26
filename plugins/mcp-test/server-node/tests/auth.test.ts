import { describe, expect, it } from 'vitest';
import { maskSecret, readIdentity } from '../src/auth.js';

describe('maskSecret', () => {
  it('파이썬과 같은 문자열을 만든다', () => {
    // 파이썬 서버가 실제로 남긴 값이다.
    expect(maskSecret('alice')).toBe('al…(sha256:2bd806c9)');
  });

  it('빈 값은 (empty)', () => {
    expect(maskSecret('')).toBe('(empty)');
  });
});

describe('readIdentity', () => {
  it('Bearer 뒤가 비면 통과시키지 않는다', () => {
    expect(readIdentity({ authorization: 'Bearer    ' })).toBeNull();
  });

  it('Authorization 이 없으면 통과시키지 않는다', () => {
    expect(readIdentity({})).toBeNull();
  });

  it('헤더가 없으면 파이썬과 같은 기본값을 쓴다', () => {
    const identity = readIdentity({ authorization: 'Bearer alice' });
    expect(identity).toEqual({
      subject: 'alice',
      instanceId: 'unknown',
      project: '',
      label: 'unnamed',
      mcpSessionId: null,
    });
  });
});
