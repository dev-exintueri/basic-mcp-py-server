/**
 * 로그 파일의 위치와 이름, 그리고 오래된 파일 청소.
 *
 * 여기 있는 함수들은 로깅이 준비되기 전에 돈다 — 디렉토리를 정해야 파일에
 * 쓸 수 있기 때문이다. 그래서 경고를 직접 남기지 않고 문자열 배열로
 * 돌려주고, 호출자가 로깅이 준비된 뒤에 남긴다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** DEFAULT_LOG_DIR, logFileName() 의 형식,
 * MAX_AGE_SECONDS 기본값.
 *
 * **함께 바꿔야 하는 것.** LOG_PATTERN 과 logFileName() 은 한 쌍이다.
 * 한쪽만 바꾸면 청소가 아무것도 찾지 못해 로그가 영영 쌓인다 — 오류는
 * 나지 않는다. PLUGIN_ID_PREFIX 는 플러그인 쪽 plugin.json 의 name 과
 * 맞물린다.
 *
 * **깨면 안 되는 것.** purgeLogs 가 LOG_PATTERN 에 맞는 파일만, 비재귀로
 * 보는 것. log_dir 은 사용자가 정하므로 홈 디렉토리를 가리킬 수도 있다 —
 * 패턴을 넓히거나 재귀로 바꾸면 남의 파일을 지운다.
 */

import {
  closeSync, fstatSync, openSync, readdirSync, readFileSync, readSync, statSync, unlinkSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

export const DEFAULT_LOG_DIR = join(homedir(), '.mcp-test-server', 'logs');
export const MAX_AGE_SECONDS = 259200; // 72시간
const LOG_PATTERN = /^mcp-test-server\..*\.log$/;

// 플러그인 ID는 <plugin-name>@<marketplace-name> 이다. 서버는 자기가 어느
// 마켓플레이스에서 설치됐는지 알 수 없으므로 접두사로만 맞춘다.
const PLUGIN_ID_PREFIX = 'mcp-test@';
export const DEFAULT_SETTINGS_PATH = join(homedir(), '.claude', 'settings.json');

/**
 * 사용자가 준 경로 문자열을 한 형태로 정규화한다.
 *
 * 물결표를 펴지 않으면 홈이 아니라 현재 디렉토리 아래에 '~' 라는 이름의
 * 디렉토리를 만들고 거기에 로그를 쌓는다.
 */
function clean(value: string): string {
  const expanded = value.startsWith('~') ? join(homedir(), value.slice(1)) : value;
  return resolve(expanded);
}

function fromSettings(settingsPath: string): { dir: string | null; warnings: string[] } {
  let raw: string;
  try {
    raw = readFileSync(settingsPath, 'utf8');
  } catch {
    return { dir: null, warnings: [] }; // 파일이 없는 것은 정상이다
  }

  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return {
      dir: null,
      warnings: [`${settingsPath} 를 JSON 으로 읽지 못했다. 로그 경로 설정을 건너뛴다`],
    };
  }

  const configs = (data as Record<string, unknown>)?.['pluginConfigs'];
  if (typeof configs !== 'object' || configs === null) return { dir: null, warnings: [] };

  const matches = Object.keys(configs).filter((k) => k.startsWith(PLUGIN_ID_PREFIX)).sort();
  if (matches.length === 0) return { dir: null, warnings: [] };

  const warnings: string[] = [];
  const chosen = matches[0]!;
  if (matches.length > 1) {
    warnings.push(`플러그인 설정이 ${matches.length}개 발견됐다. ${chosen} 를 쓴다`);
  }

  const entry = (configs as Record<string, unknown>)[chosen];
  const options = (entry as Record<string, unknown>)?.['options'];
  if (typeof options !== 'object' || options === null) return { dir: null, warnings };

  const value = (options as Record<string, unknown>)['log_dir'];
  if (value === undefined || value === null) return { dir: null, warnings };
  if (typeof value !== 'string') {
    warnings.push(`플러그인 설정의 log_dir 이 문자열이 아니다: ${JSON.stringify(value)}`);
    return { dir: null, warnings };
  }
  if (!value.trim()) {
    warnings.push('플러그인 설정의 log_dir 이 비어 있다');
    return { dir: null, warnings };
  }
  return { dir: clean(value), warnings };
}

/** 로그 디렉토리를 정한다. 앞이 이긴다: --log-dir > $MCP_TEST_LOG_DIR > settings.json > 기본값 */
export function resolveLogDir(options: {
  flag: string | null;
  env: string | undefined;
  settingsPath?: string;
}): { dir: string; warnings: string[] } {
  if (options.flag && options.flag.trim()) return { dir: clean(options.flag), warnings: [] };
  if (options.env && options.env.trim()) return { dir: clean(options.env), warnings: [] };

  const { dir, warnings } = fromSettings(options.settingsPath ?? DEFAULT_SETTINGS_PATH);
  if (dir !== null) return { dir, warnings };
  return { dir: DEFAULT_LOG_DIR, warnings };
}

export function logFileName(port: number, day: Date): string {
  const iso = day.toISOString().slice(0, 10);
  return `mcp-test-server.${port}.${iso}.log`;
}

export function purgeLogs(
  logDir: string,
  now: Date,
  options: { maxAgeSeconds?: number; keep?: string | null } = {},
): { removed: number; warnings: string[] } {
  const maxAge = options.maxAgeSeconds ?? MAX_AGE_SECONDS;
  const keep = options.keep ? resolve(options.keep) : null;
  const cutoff = now.getTime() / 1000 - maxAge;

  let entries: string[];
  try {
    entries = readdirSync(logDir).filter((name) => LOG_PATTERN.test(name)).sort();
  } catch {
    return { removed: 0, warnings: [] };
  }

  let removed = 0;
  const warnings: string[] = [];
  for (const name of entries) {
    const path = join(logDir, name);
    if (keep !== null && resolve(path) === keep) continue;
    try {
      const info = statSync(path);
      if (!info.isFile()) continue;
      if (info.mtimeMs / 1000 >= cutoff) continue;
      unlinkSync(path);
    } catch (error) {
      warnings.push(`오래된 로그 ${path} 를 지우지 못했다: ${String(error)}`);
      continue;
    }
    removed += 1;
  }
  return { removed, warnings };
}

/** 파일 끝에서 최대 maxBytes 를 읽어 마지막 lines 줄을 돌려준다. */
export function tailLines(
  path: string,
  options: { lines?: number; maxBytes?: number } = {},
): string[] {
  const wanted = options.lines ?? 200;
  const maxBytes = options.maxBytes ?? 65536;
  let fd: number | undefined;
  try {
    fd = openSync(path, 'r');
    const size = fstatSync(fd).size;
    const start = Math.max(0, size - maxBytes);
    const length = size - start;
    const buffer = Buffer.alloc(length);
    readSync(fd, buffer, 0, length, start);
    let text = buffer.toString('utf8');
    // 잘린 첫 줄은 반쪽이라 버린다. 읽어온 범위에 개행이 아예 없으면
    // (마지막 줄 하나가 maxBytes 를 통째로 넘는 경우) 그 반쪽 전체를
    // 버린다 — indexOf 가 -1 일 때 +1 로 0 을 만들어 버리면 자른 텍스트를
    // 그대로 남기게 되어, 파이썬 str.partition() 의 결과(빈 문자열)와
    // 달라진다.
    if (size > maxBytes) {
      const cut = text.indexOf('\n');
      text = cut === -1 ? '' : text.slice(cut + 1);
    }
    return text.split('\n').filter((l) => l !== '').slice(-wanted);
  } catch {
    return [];
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}
