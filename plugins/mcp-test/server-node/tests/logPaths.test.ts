import { mkdtempSync, writeFileSync, utimesSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { DEFAULT_LOG_DIR, logFileName, purgeLogs, resolveLogDir } from '../src/logPaths.js';

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
