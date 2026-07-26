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
 * 빈 문자열·공백만인 문자열은 먼저 거부한다. `Number('')` 와
 * `Number('   ')` 는 자바스크립트에서 0이라, 이 가드가 없으면
 * `--port ''` 가 requireInt() 를 조용히 통과해 포트 0(임의 포트)으로
 * 뜬다. 파이썬 argparse 는 `int('')` 에서 ValueError 를 내고 exit 2로
 * 거부하므로(conformance/test_cli.py 의 test_empty_numeric_flag_is_rejected
 * 가 실측), 두 런타임을 맞추려면 숫자로 변환하기 전에 공백을 먼저 본다.
 *
 * 파일 끝의 실행 가드(`process.argv[1] === fileURLToPath(import.meta.url)`)
 * 는 파이썬의 `if __name__ == "__main__":` 과 같은 역할이다. parseArgs() 를
 * 테스트가 import 할 때 실 서버가 뜨는 부작용 없이 함수만 가져오려면
 * 반드시 있어야 한다 — 지우면 `node --test` 든 vitest 든 이 모듈을 import
 * 하는 순간 실제로 포트를 문다.
 *
 * `process.on('unhandledRejection'/'uncaughtException')` 을 여기 두는 이유는
 * 진입점이라서다 — 등록은 프로세스 전체에 한 번이면 되고, 모듈을 import 할
 * 때마다 다시 걸릴 필요가 없다. 파이썬 `app.py` 의 `_loop_exception_handler`
 * 와 자리가 맞는다: 그쪽은 태스크 안에서 난 예외가 `main()` 까지 올라오지
 * 않고 `loop.set_exception_handler()` 에 잡혀 로그만 남고 나머지 서버는
 * 계속 도는 것을 확인한 뒤(purge 태스크가 죽어도 mcp/admin 리스너는 안
 * 죽는다), 두 핸들러 모두 **프로세스를 내리지 않는다** — 로그만 남기고
 * 계속 돈다. Node 커뮤니티의 일반적인 조언(uncaughtException 뒤에는 상태를
 * 못 믿으니 내려야 한다)과 다르게 간 것은 의도적이다 — 파이썬 쪽과
 * "밖에서 구별되지 않는다"는 계약을 지키려면, 여기서 예외를 하나 삼켰다고
 * 서버 전체가 죽어서는 안 된다.
 */

import { parseArgs as nodeParseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';

import { DEFAULTS, serve } from './app.js';
import {
  configureLogging, dailyFileSink, ensureLogDir, getLogger, type Clock, type Sink,
} from './logging.js';
import { resolveLogDir } from './logPaths.js';
import { LogBroadcaster } from './logStream.js';

export interface Options {
  host: string;
  port: number;
  adminPort: number;
  staleAfter: number;
  logDir: string | null;
  logRetentionDays: number;
}

// Number('') 와 Number('   ') 는 0이다. 빈 문자열·공백만인 문자열을 숫자로
// 바꾸기 전에 걸러낸다 — 걸러내지 않으면 "값을 안 준 것"과 "0을 준 것"이
// 구별되지 않는다.
function isBlank(raw: string): boolean {
  return raw.trim() === '';
}

// 파이썬 argparse 의 type=int 를 흉내 낸다: 정수가 아니면(소수점 포함)
// 거부하지만, 음수나 0 은 그대로 통과시킨다 — argparse 도 그 값을 받아들이고
// 나중에 listen() 이 실패하게 둔다. 여기서 막으면 파이썬보다 더 엄격해진다.
function requireInt(name: string, raw: string | undefined, fallback: number): number {
  if (raw !== undefined && isBlank(raw)) {
    throw new Error(`--${name} 은(는) 정수여야 한다`);
  }
  const value = Number(raw ?? fallback);
  if (!Number.isInteger(value)) {
    throw new Error(`--${name} 은(는) 정수여야 한다`);
  }
  return value;
}

// 파이썬 argparse 의 type=float 를 흉내 낸다: 숫자로 못 읽을 때만 거부한다.
function requireFloat(name: string, raw: string | undefined, fallback: number): number {
  if (raw !== undefined && isBlank(raw)) {
    throw new Error(`--${name} 은(는) 숫자여야 한다`);
  }
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

  const { dir: logDir, warnings } = resolveLogDir({
    flag: options.logDir,
    env: process.env['MCP_TEST_LOG_DIR'],
  });

  const broadcaster = new LogBroadcaster();
  const sinks: Sink[] = [(line) => broadcaster.publish(line)];
  let currentPath: (() => string) | null = null;

  if (ensureLogDir(logDir)) {
    const file = dailyFileSink(logDir, options.port, clock);
    sinks.push(file.sink);
    currentPath = file.currentPath;
  }
  configureLogging({ clock, sinks });

  // 파이썬 app.py 의 _loop_exception_handler 와 자리가 맞는다 — 어디서도
  // 안 잡힌 예외가 stderr 로만 새서 로그 파일에도 SSE 스트림에도 안 남는
  // 상태를 막는다. 프로세스는 내리지 않는다. 이유는 위 모듈 주석에 있다.
  // configureLogging() 뒤에 등록해야 getLogger() 가 실제로 어딘가에 쓴다.
  const crashLogger = getLogger('app');
  process.on('unhandledRejection', (reason) => {
    const message = reason instanceof Error ? reason.message : String(reason);
    crashLogger.error(`처리되지 않은 프로미스 거부: ${message}`);
  });
  process.on('uncaughtException', (error) => {
    crashLogger.error(`처리되지 않은 예외: ${error.message}`);
  });

  // 경로를 정하는 동안에는 남길 곳이 없었다. 준비된 뒤에 남긴다.
  for (const message of warnings) getLogger('app').warn(message);

  const handle = await serve({
    host: options.host,
    port: options.port,
    adminPort: options.adminPort,
    staleAfter: options.staleAfter,
    clock,
    broadcaster,
    logDir: currentPath === null ? null : logDir,
    logFile: () => (currentPath === null ? null : currentPath()),
    logMaxAgeSeconds: options.logRetentionDays * 86400,
  });

  // 이것이 없으면 shouldStop 이 영원히 false 다. 노드의 기본 신호 처리는
  // 즉시 프로세스를 끝내므로 매달리지는 않지만, 그러면 close() 안의 정리
  // (purge 타이머, 열린 SSE 응답)가 한 번도 돌지 않고 shouldStop 은
  // 아무도 당기지 않는 배관이 된다.
  //
  // 적합성 스위트의 픽스처가 SIGTERM 을 보내므로 이 경로는 매 테스트마다
  // 실제로 돈다.
  //
  // .catch() 가 반드시 있어야 한다. close() 가 거부되면(예: 두 서버 중
  // 하나의 close 콜백에서 예외) 이 체인이 unhandled rejection 이 되는데,
  // 이 시점엔 process.once(signal, ...) 가 이미 자기 핸들러를 뗀 뒤라 —
  // 프로세스가 그대로 눌러앉아 정상 종료였어야 할 것이 매달리거나, 위
  // unhandledRejection 핸들러가 로그만 남기고 종료 코드 0 으로 이어지지
  // 않는다. 실패 시엔 명시적으로 비정상 종료 코드를 낸다.
  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    process.once(signal, () => {
      void handle
        .close()
        .then(() => process.exit(0))
        .catch(() => process.exit(1));
    });
  }
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
