/**
 * CLI 진입점.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** CLI 인자. 새 인자는 parseArgs() 에 더하고 serve() 로
 * 넘긴다.
 *
 * **깨면 안 되는 것.** 실제 시계를 만드는 곳은 여기뿐이다. 다른 모듈은
 * clock 을 주입받는다.
 *
 * **함께 바꿔야 하는 것.** requireInt()/requireFloat() 는 파이썬
 * argparse 의 `type=int`/`type=float` 를 흉내 낸다 — port/admin-port 는
 * 정수가 아니면(소수점 포함) 거부하지만 음수·0 은 그대로 받는다(그 값은
 * listen() 이 나중에 거부한다). stale-after 는 숫자가 아닐 때만 거부한다.
 * 새 숫자 인자를 추가한다면 파이썬 __main__.py 의 add_argument 타입을 먼저
 * 확인하고 어느 쪽을 쓸지 정한다.
 *
 * 파일 끝의 실행 가드(`process.argv[1] === fileURLToPath(import.meta.url)`)
 * 는 파이썬의 `if __name__ == "__main__":` 과 같은 역할이다. parseArgs() 를
 * 테스트가 import 할 때 실 서버가 뜨는 부작용 없이 함수만 가져오려면
 * 반드시 있어야 한다 — 지우면 `node --test` 든 vitest 든 이 모듈을 import
 * 하는 순간 실제로 포트를 문다.
 */

import { parseArgs as nodeParseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';

import { DEFAULTS, serve } from './app.js';
import { configureLogging, type Clock } from './logging.js';

export interface Options {
  host: string;
  port: number;
  adminPort: number;
  staleAfter: number;
  logDir: string | null;
  logRetentionDays: number;
}

// 파이썬 argparse 의 type=int 를 흉내 낸다: 정수가 아니면(소수점 포함)
// 거부하지만, 음수나 0 은 그대로 통과시킨다 — argparse 도 그 값을 받아들이고
// 나중에 listen() 이 실패하게 둔다. 여기서 막으면 파이썬보다 더 엄격해진다.
function requireInt(name: string, raw: string | undefined, fallback: number): number {
  const value = Number(raw ?? fallback);
  if (!Number.isInteger(value)) {
    throw new Error(`--${name} 은(는) 정수여야 한다`);
  }
  return value;
}

// 파이썬 argparse 의 type=float 를 흉내 낸다: 숫자로 못 읽을 때만 거부한다.
function requireFloat(name: string, raw: string | undefined, fallback: number): number {
  const value = Number(raw ?? fallback);
  if (Number.isNaN(value)) {
    throw new Error(`--${name} 은(는) 숫자여야 한다`);
  }
  return value;
}

export function parseArgs(argv: string[]): Options {
  const { values } = nodeParseArgs({
    args: argv,
    options: {
      host: { type: 'string' },
      port: { type: 'string' },
      'admin-port': { type: 'string' },
      'stale-after': { type: 'string' },
      'log-dir': { type: 'string' },
      'log-retention-days': { type: 'string' },
    },
  });

  const retention = Number(values['log-retention-days'] ?? 3);
  if (!Number.isInteger(retention) || retention <= 0) {
    // 0을 허용하면 방금 쓴 줄이 다음 스윕에 지워진다.
    throw new Error('--log-retention-days 는 1 이상의 정수여야 한다');
  }

  return {
    host: values.host ?? DEFAULTS.host,
    port: requireInt('port', values.port, DEFAULTS.port),
    adminPort: requireInt('admin-port', values['admin-port'], DEFAULTS.adminPort),
    staleAfter: requireFloat('stale-after', values['stale-after'], DEFAULTS.staleAfter),
    logDir: values['log-dir'] ?? null,
    logRetentionDays: retention,
  };
}

async function main(): Promise<number> {
  let options: Options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${(error as Error).message}\n`);
    return 2;
  }

  const clock: Clock = () => new Date();
  configureLogging({
    clock,
    sinks: [(line) => process.stdout.write(line + '\n')],
  });

  await serve({
    host: options.host,
    port: options.port,
    adminPort: options.adminPort,
    staleAfter: options.staleAfter,
    clock,
  });
  return 0;
}

// CLI 로 직접 실행됐을 때만 뜬다. import 만으로는 뜨지 않는다 — parseArgs()
// 를 가져다 쓰는 테스트가 실제 서버를 띄우지 않게 하기 위해서다.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().then(
    (code) => {
      if (code !== 0) process.exit(code);
    },
    (error) => {
      process.stderr.write(`${String(error)}\n`);
      process.exit(1);
    },
  );
}
