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
 */

import { parseArgs as nodeParseArgs } from 'node:util';

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
    port: Number(values.port ?? DEFAULTS.port),
    adminPort: Number(values['admin-port'] ?? DEFAULTS.adminPort),
    staleAfter: Number(values['stale-after'] ?? DEFAULTS.staleAfter),
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

main().then(
  (code) => {
    if (code !== 0) process.exit(code);
  },
  (error) => {
    process.stderr.write(`${String(error)}\n`);
    process.exit(1);
  },
);
