import {
  existsSync, mkdirSync, mkdtempSync, writeFileSync, utimesSync, readdirSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { isAbsolute, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  DEFAULT_LOG_DIR, logFileName, purgeLogs, resolveLogDir, tailLines,
} from '../src/logPaths.js';

describe('logFileName', () => {
  it('포트와 날짜로 이름을 만든다', () => {
    expect(logFileName(8765, new Date('2026-07-26T10:00:00Z'))).toBe(
      'mcp-test-server.8765.2026-07-26.log',
    );
  });
});

describe('purgeLogs', () => {
  it('패턴에 맞지 않는 파일은 건드리지 않는다', () => {
    // log_dir 은 사용자가 정한다. 홈 디렉토리를 가리켜도 안전해야 한다.
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const old = new Date('2020-01-01T00:00:00Z');

    writeFileSync(join(dir, 'mcp-test-server.8765.2020-01-01.log'), 'x');
    writeFileSync(join(dir, '중요한파일.txt'), 'x');
    for (const name of readdirSync(dir)) {
      utimesSync(join(dir, name), old, old);
    }

    const { removed } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'), {
      maxAgeSeconds: 259200,
      keep: null,
    });

    expect(removed).toBe(1);
    expect(readdirSync(dir)).toEqual(['중요한파일.txt']);
  });

  it('열려 있는 파일은 남긴다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const old = new Date('2020-01-01T00:00:00Z');
    const keep = join(dir, 'mcp-test-server.8765.2020-01-01.log');
    writeFileSync(keep, 'x');
    utimesSync(keep, old, old);

    const { removed } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'), {
      maxAgeSeconds: 259200,
      keep,
    });

    expect(removed).toBe(0);
    expect(readdirSync(dir)).toEqual(['mcp-test-server.8765.2020-01-01.log']);
  });
});

describe('resolveLogDir', () => {
  // 이 층은 적합성 스위트가 닿을 수 없다 — 스위트는 CLI 와 HTTP 로만
  // 서버를 몰고, 이 경로는 홈 디렉토리에 하드코딩돼 있다. 설계 문서가
  // "노드 단위 테스트가 보증한다" 고 적은 부분이 여기다.
  function withSettings(contents: string): string {
    const dir = mkdtempSync(join(tmpdir(), 'settings-'));
    const path = join(dir, 'settings.json');
    writeFileSync(path, contents, 'utf8');
    return path;
  }

  it('플러그인 설정의 log_dir 을 읽는다', () => {
    const settingsPath = withSettings(
      JSON.stringify({
        pluginConfigs: {
          'mcp-test@basic-mcp-py-server': { options: { log_dir: '/tmp/from-settings' } },
        },
      }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe('/tmp/from-settings');
    expect(warnings).toEqual([]);
  });

  it('플래그가 설정을 이긴다', () => {
    const settingsPath = withSettings(
      JSON.stringify({
        pluginConfigs: { 'mcp-test@x': { options: { log_dir: '/tmp/from-settings' } } },
      }),
    );
    const { dir } = resolveLogDir({ flag: '/tmp/from-flag', env: undefined, settingsPath });
    expect(dir).toBe('/tmp/from-flag');
  });

  it('환경 변수가 설정을 이긴다', () => {
    const settingsPath = withSettings(
      JSON.stringify({
        pluginConfigs: { 'mcp-test@x': { options: { log_dir: '/tmp/from-settings' } } },
      }),
    );
    const { dir } = resolveLogDir({ flag: null, env: '/tmp/from-env', settingsPath });
    expect(dir).toBe('/tmp/from-env');
  });

  it('망가진 JSON 은 경고하고 기본값으로 떨어진다', () => {
    const settingsPath = withSettings('{ 이건 JSON 이 아니다');
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain('JSON');
    expect(dir).toBe(DEFAULT_LOG_DIR);
  });

  it('log_dir 이 문자열이 아니면 경고한다', () => {
    const settingsPath = withSettings(
      JSON.stringify({ pluginConfigs: { 'mcp-test@x': { options: { log_dir: 42 } } } }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(warnings[0]).toContain('문자열이 아니다');
    expect(dir).toBe(DEFAULT_LOG_DIR);
  });

  it('설정 파일이 없는 것은 정상이다', () => {
    const { dir, warnings } = resolveLogDir({
      flag: null,
      env: undefined,
      settingsPath: '/이런/경로는/없다/settings.json',
    });
    expect(warnings).toEqual([]);
    expect(dir).toBe(DEFAULT_LOG_DIR);
  });
});

// --- 커버리지 보강: 파이썬 tests/test_logpaths.py 를 이식한다 ---
//
// 브리프의 9개는 각 함수의 대표 경로만 덮는다. 아래는 파이썬 기준 구현이
// 고정하는데 브리프가 놓친 동작이다. 기계적으로 26개를 베끼지 않고, 이
// 저장소의 노드 구현에서 실제로 성립하는 것만 옮긴다.

describe('resolveLogDir (커버리지 보강)', () => {
  function withSettings(contents: string): string {
    const dir = mkdtempSync(join(tmpdir(), 'settings-'));
    const path = join(dir, 'settings.json');
    writeFileSync(path, contents, 'utf8');
    return path;
  }

  it('물결표와 상대 경로를 절대 경로로 편다', () => {
    // clean() 의 expanduser 상당 부분. 이걸 지우면 '~/x' 가 글자 그대로
    // 남아 현재 디렉토리 아래에 '~' 라는 이름의 디렉토리를 만든다.
    const { dir } = resolveLogDir({
      flag: '~/somewhere',
      env: undefined,
      settingsPath: '/이런/경로는/없다/settings.json',
    });
    expect(isAbsolute(dir)).toBe(true);
    expect(dir).not.toContain('~');
  });

  it('pluginConfigs 키 자체가 없으면 조용히 기본값으로 간다', () => {
    const settingsPath = withSettings(JSON.stringify({ model: 'opus' }));
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe(DEFAULT_LOG_DIR);
    expect(warnings).toEqual([]);
  });

  it('접두사에 맞는 플러그인 설정이 없으면 조용히 기본값으로 간다', () => {
    const settingsPath = withSettings(
      JSON.stringify({ pluginConfigs: { 'other@market': { options: { log_dir: '/x' } } } }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe(DEFAULT_LOG_DIR);
    expect(warnings).toEqual([]);
  });

  it('맞는 키가 있어도 log_dir 이 없으면 조용히 기본값으로 간다', () => {
    // 설치는 됐으나 이 항목만 미설정한 정상 상태다. 실패로 취급하지 않는다.
    const settingsPath = withSettings(
      JSON.stringify({ pluginConfigs: { 'mcp-test@m': { options: {} } } }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe(DEFAULT_LOG_DIR);
    expect(warnings).toEqual([]);
  });

  it('접두사가 맞는 키가 둘이면 정렬된 첫 번째를 쓰고 경고한다', () => {
    const settingsPath = withSettings(
      JSON.stringify({
        pluginConfigs: {
          'mcp-test@zzz': { options: { log_dir: '/from/zzz' } },
          'mcp-test@aaa': { options: { log_dir: '/from/aaa' } },
        },
      }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe(resolve('/from/aaa'));
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain('mcp-test@aaa');
  });

  it('log_dir 이 공백뿐이면 경고하고 기본값으로 떨어진다', () => {
    const settingsPath = withSettings(
      JSON.stringify({ pluginConfigs: { 'mcp-test@x': { options: { log_dir: '   ' } } } }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe(DEFAULT_LOG_DIR);
    expect(warnings).toHaveLength(1);
  });

  it('log_dir 이 null 이면 조용히 기본값으로 간다', () => {
    const settingsPath = withSettings(
      JSON.stringify({ pluginConfigs: { 'mcp-test@x': { options: { log_dir: null } } } }),
    );
    const { dir, warnings } = resolveLogDir({ flag: null, env: undefined, settingsPath });
    expect(dir).toBe(DEFAULT_LOG_DIR);
    expect(warnings).toEqual([]);
  });
});

describe('purgeLogs (커버리지 보강)', () => {
  it('다른 포트의 로그도 청소 대상이다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const old = new Date('2020-01-01T00:00:00Z');
    const path = join(dir, 'mcp-test-server.9999.2020-01-01.log');
    writeFileSync(path, 'x');
    utimesSync(path, old, old);

    const { removed } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'));

    expect(removed).toBe(1);
  });

  it('디렉토리가 없으면 조용히 아무 일도 하지 않는다', () => {
    const parent = mkdtempSync(join(tmpdir(), 'purge-'));
    const dir = join(parent, 'absent');

    const { removed, warnings } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'));

    expect(removed).toBe(0);
    expect(warnings).toEqual([]);
  });

  it('하위 디렉토리로는 재귀로 내려가지 않고, 글롭에 안 맞는 이름은 건드리지 않는다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const old = new Date('2020-01-01T00:00:00Z');

    const nested = join(dir, 'sub');
    mkdirSync(nested);
    const deep = join(nested, 'mcp-test-server.1.2020-01-01.log');
    writeFileSync(deep, 'x');
    utimesSync(deep, old, old);

    // 포트·날짜 세그먼트가 없어 LOG_PATTERN 에 맞지 않는다.
    const notOurs = join(dir, 'mcp-test-server.log');
    writeFileSync(notOurs, 'x');
    utimesSync(notOurs, old, old);

    const { removed } = purgeLogs(dir, new Date('2026-07-26T00:00:00Z'));

    expect(removed).toBe(0);
    expect(existsSync(deep)).toBe(true);
    expect(existsSync(notOurs)).toBe(true);
  });

  it('보관 기간을 하루로 주면 이틀 지난 파일만 지우고 12시간 파일은 남긴다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const now = new Date('2026-07-26T12:00:00Z');
    const oldPath = join(dir, logFileName(8765, new Date('2026-07-24T12:00:00Z')));
    const freshPath = join(dir, logFileName(8765, new Date('2026-07-26T12:00:00Z')));
    writeFileSync(oldPath, 'x');
    writeFileSync(freshPath, 'x');
    const oldStamp = new Date(now.getTime() - 48 * 3600_000);
    const freshStamp = new Date(now.getTime() - 12 * 3600_000);
    utimesSync(oldPath, oldStamp, oldStamp);
    utimesSync(freshPath, freshStamp, freshStamp);

    const { removed } = purgeLogs(dir, now, { maxAgeSeconds: 1 * 86400 });

    expect(removed).toBe(1);
    expect(existsSync(oldPath)).toBe(false);
    expect(existsSync(freshPath)).toBe(true);
  });

  it('maxAgeSeconds 를 생략하면 기본 72시간이 유지된다 (회귀)', () => {
    const dir = mkdtempSync(join(tmpdir(), 'purge-'));
    const now = new Date('2026-07-26T12:00:00Z');
    const insidePath = join(dir, logFileName(8765, new Date('2026-07-24T12:00:00Z'))); // 71시간 전
    const outsidePath = join(dir, logFileName(8765, new Date('2026-07-22T12:00:00Z'))); // 73시간 전
    writeFileSync(insidePath, 'x');
    writeFileSync(outsidePath, 'x');
    const insideStamp = new Date(now.getTime() - 71 * 3600_000);
    const outsideStamp = new Date(now.getTime() - 73 * 3600_000);
    utimesSync(insidePath, insideStamp, insideStamp);
    utimesSync(outsidePath, outsideStamp, outsideStamp);

    const { removed } = purgeLogs(dir, now);

    expect(removed).toBe(1);
    expect(existsSync(insidePath)).toBe(true);
    expect(existsSync(outsidePath)).toBe(false);
  });
});

describe('tailLines (커버리지 보강 — 브리프에 테스트가 0개였다)', () => {
  it('마지막 n 줄만 돌려준다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'tail-'));
    const path = join(dir, 'a.log');
    writeFileSync(path, Array.from({ length: 500 }, (_, i) => `line${i}`).join('\n'));

    expect(tailLines(path, { lines: 3 })).toEqual(['line497', 'line498', 'line499']);
  });

  it('잘린 첫 줄은 버린다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'tail-'));
    const path = join(dir, 'b.log');
    writeFileSync(path, 'A'.repeat(100) + '\n' + 'B'.repeat(20) + '\n');

    expect(tailLines(path, { lines: 10, maxBytes: 50 })).toEqual(['B'.repeat(20)]);
  });

  it('읽어온 것이 전부 반쪽 줄이면 남길 온전한 줄이 없다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'tail-'));
    const path = join(dir, 'c.log');
    writeFileSync(path, 'B'.repeat(100));

    expect(tailLines(path, { lines: 10, maxBytes: 50 })).toEqual([]);
  });

  it('없는 파일은 빈 배열을 돌려준다', () => {
    const dir = mkdtempSync(join(tmpdir(), 'tail-'));

    expect(tailLines(join(dir, 'absent.log'))).toEqual([]);
  });

  it('seek 오프셋이 정확하다', () => {
    // 고정폭 번호 줄로 오프셋을 손으로 계산 가능하게 만든다.
    // 파일: "0000\n0001\n...0049\n" = 50줄 x 5바이트 = 250바이트
    // maxBytes: 60, offset: 250-60=190 (줄38 중간)
    // 읽은 데이터는 줄38 일부 + 줄39-49 이고, 첫 개행 앞을 버리면 줄39-49 만 남는다.
    const dir = mkdtempSync(join(tmpdir(), 'tail-'));
    const path = join(dir, 'd.log');
    const lines = Array.from({ length: 50 }, (_, i) => `${String(i).padStart(4, '0')}\n`);
    writeFileSync(path, lines.join(''));

    const result = tailLines(path, { lines: 20, maxBytes: 60 });
    const expected = Array.from({ length: 11 }, (_, i) => String(i + 39).padStart(4, '0'));
    expect(result).toEqual(expected);
  });
});
