/**
 * 두 리스너를 조립하고 한 프로세스에서 함께 기동한다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** DEFAULTS 의 포트와 유휴 기준, 그리고 buildMcpApp() 이
 * 무엇을 무엇으로 감싸는지. 미들웨어를 더한다면 거기다.
 *
 * **깨면 안 되는 것.**
 *
 * - accessLog() 를 authMiddleware() 보다 **먼저** 등록한다. 순서가 곧
 *   바깥/안쪽이다.
 * - 관리 리스너의 주소는 ADMIN_HOST 고정이다. 인증이 없는 리스너이므로
 *   바꿀 수 있는 통로를 만들지 않는다.
 * - createMcpExpressApp() 을 쓰지 않는다. 그 헬퍼는 Host 헤더 검증을
 *   자동으로 걸어 파이썬 서버와 동작이 갈린다.
 * - serve() 의 close() 는 shuttingDown 을 가장 먼저 true 로 만든다.
 *   /api/logs/stream 의 while 루프가 그 값을 폴링해 스스로 끝나야 하는데,
 *   순서를 바꿔 서버부터 닫으면 열려 있는 SSE 응답이 종료를 막는다.
 * - close() 는 GRACEFUL_SHUTDOWN_MS 상한을 반드시 둔다. 관리 포트의 SSE
 *   로그 스트림과 MCP 포트의 알림용 GET 스트림 둘 다 응답을 무한정 붙들 수
 *   있는 장수 연결이다 — 클라이언트가 쓰기 버퍼를 실제로 막아 두면(느린
 *   리더가 응답을 안 읽는 상태로 부하가 쌓이면) `server.close()` 콜백은
 *   그 소켓이 스스로 끝나기 전까지 영원히 안 온다(실측: 리뷰가 멈춘 리더 +
 *   800KB 이상에서 SIGKILL 매달림을 재현했다). 상한을 넘기면
 *   `closeAllConnections()` 로 남은 연결을 강제로 끊는다 — 파이썬 app.py 의
 *   `_GRACEFUL_SHUTDOWN_SECONDS` → `timeout_graceful_shutdown` 과 같은
 *   자리, 같은 값이다. 그 독스트링이 "이 값이 없으면 프로세스가 영영
 *   끝나지 않는다" 고 적은 것과 동일한 이유다.
 *
 * **함께 바꿔야 하는 것.** isLoopback() 은 파이썬 app.py 의 is_loopback()
 * (표준 라이브러리 ipaddress.ip_address(...).is_loopback 판정)을 흉내
 * 낸다 — 127.0.0.0/8 전체, ::1, IPv4-mapped IPv6(::ffff:127.x.x.x), 그리고
 * "localhost" 문자열이 참이다. 이 판정을 바꾸면 파이썬 쪽 test_app.py 의
 * 파라미터라이즈 표와 tests/app.test.ts 의 표를 함께 봐야 한다 — 두 표는
 * 같은 입력·출력 쌍이어야 "밖에서 구별되지 않는다"는 계약이 유지된다.
 */

import express from 'express';
import type { Express } from 'express';
import { createServer, type Server } from 'node:http';
import { isIPv4, isIPv6 } from 'node:net';

import { accessLog } from './access.js';
import { authMiddleware } from './auth.js';
import { getLogger, type Clock } from './logging.js';
import { purgeLogs } from './logPaths.js';
import type { LogBroadcaster } from './logStream.js';
import { buildMcp } from './mcpServer.js';
import { mcpRoute } from './mcpRoute.js';
import { Registry } from './registry.js';
import { buildAdminApp } from './admin.js';

const logger = getLogger('app');

// 관리 리스너는 루프백에 고정한다. 인증이 없는 리스너이므로 이 값을 바꿀 수
// 있는 통로를 만들지 않는다.
export const ADMIN_HOST = '127.0.0.1';

export const DEFAULTS = {
  host: '127.0.0.1',
  port: 8765,
  adminPort: 8766,
  staleAfter: 300.0,
};

const WILDCARD_HOSTS = new Set(['0.0.0.0', '::']);

// 파이썬 app.py 의 _GRACEFUL_SHUTDOWN_SECONDS(=3)와 같은 값이다. 진행 중인
// 짧은 요청이 응답을 마치기엔 넉넉하고, 사람이 종료를 기다리기엔 짧다.
const GRACEFUL_SHUTDOWN_MS = 3000;

// ::ffff:a.b.c.d 형태의 IPv4-mapped IPv6 주소에서 매핑된 IPv4 부분을 꺼낸다.
// 파이썬 ipaddress.IPv6Address.is_loopback 은 이 형태를 만나면 매핑된
// IPv4 주소의 is_loopback 을 대신 본다 — 그 판정을 그대로 흉내 낸다.
const IPV4_MAPPED = /^::ffff:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$/i;

function ipv4IsLoopback(host: string): boolean {
  // 127.0.0.0/8 전체가 루프백이다. 첫 옥텟만 보면 된다.
  return host.split('.', 1)[0] === '127';
}

export function isLoopback(host: string): boolean {
  if (isIPv4(host)) return ipv4IsLoopback(host);
  if (isIPv6(host)) {
    const mapped = IPV4_MAPPED.exec(host);
    if (mapped) return ipv4IsLoopback(mapped[1]);
    return host === '::1';
  }
  return host.toLowerCase() === 'localhost';
}

/** 바인딩 주소를 클라이언트가 실제로 접속할 수 있는 주소로 바꾼다. */
export function endpointHost(host: string): string {
  return WILDCARD_HOSTS.has(host) ? '127.0.0.1' : host;
}

/**
 * 루프백 밖에 노출될 때 보여줄 경고문. 안전하면 null.
 *
 * serve() 안에 인라인으로 두면 경고 여부를 판단하는 규칙을 테스트가 확인할
 * 수 없다. 아무것도 출력하지 않는 순수 함수로 떼어 둔다.
 */
export function exposureWarning(host: string): string | null {
  if (isLoopback(host)) return null;
  return (
    `경고: ${host} 는 루프백 주소가 아니다. 이 서버의 인증은 비어 있지 않은 ` +
    'Bearer 토큰이면 무엇이든 통과시키므로, 이 포트에 닿을 수 있는 사람은 ' +
    '누구나 연결된 모든 세션의 프로젝트 경로와 토큰을 읽고 세션을 지울 수 ' +
    '있다. 신뢰할 수 없는 망에서는 쓰지 마라.'
  );
}

export interface ServeOptions {
  host: string;
  port: number;
  adminPort: number;
  staleAfter: number;
  clock: Clock;
  broadcaster: LogBroadcaster | null;
  logDir: string | null;
  logFile: () => string | null;
  logMaxAgeSeconds: number;
}

export function buildMcpApp(registry: Registry, startedAt: Date, clock: Clock): Express {
  const app = express();
  // 순서가 계약이다. 접근 로그가 바깥, 인증이 안쪽.
  app.use(accessLog());
  // express.json() 은 POST 에만 건다. GET(알림용 SSE 스트림)까지 걸면
  // transport 가 읽어야 할 스트림이 소진된다.
  app.post('/mcp', express.json());
  app.use(authMiddleware(registry, clock));

  const route = mcpRoute(() => buildMcp(registry, startedAt, clock));
  app.post('/mcp', route);
  app.get('/mcp', route);
  app.delete('/mcp', route);
  return app;
}

export async function serve(options: ServeOptions): Promise<{ close: () => Promise<void> }> {
  const warning = exposureWarning(options.host);
  if (warning !== null) {
    process.stderr.write(warning + '\n');
    logger.warn(warning);
  }

  const startedAt = options.clock();
  const registry = new Registry(options.staleAfter);
  const mcpApp = buildMcpApp(registry, startedAt, options.clock);

  const mcpServer = createServer(mcpApp);
  await listen(mcpServer, options.port, options.host);

  process.stdout.write(`MCP    http://${options.host}:${options.port}/mcp\n`);
  logger.info(
    `서버 기동 MCP=${options.host}:${options.port} 관리=${ADMIN_HOST}:${options.adminPort}`,
  );

  // close() 가 맨 먼저 이 값을 true 로 만든다. /api/logs/stream 의 루프가
  // 이 값을 폴링해 스스로 끝나야, 열려 있는 SSE 응답이 종료를 막지 않는다.
  let shuttingDown = false;

  const adminApp = buildAdminApp({
    registry,
    startedAt,
    clock: options.clock,
    mcpEndpoint: `http://${endpointHost(options.host)}:${options.port}/mcp`,
    runtime: 'node',
    broadcaster: options.broadcaster,
    logFile: options.logFile,
    shouldStop: () => shuttingDown,
  });
  const adminServer = createServer(adminApp);
  await listen(adminServer, options.adminPort, ADMIN_HOST);

  process.stdout.write(`관리   http://${ADMIN_HOST}:${options.adminPort}/\n`);

  if (options.logDir !== null) {
    process.stdout.write(`로그   ${options.logFile()}\n`);
    // 기동 직후 한 번 청소한다. 아래 주기 타이머는 10분 뒤에야 처음 돈다.
    const { warnings } = purgeLogs(options.logDir, options.clock(), {
      maxAgeSeconds: options.logMaxAgeSeconds,
      keep: options.logFile(),
    });
    for (const message of warnings) logger.warn(message);
  }

  const purgeTimer = setInterval(() => {
    const now = options.clock();
    const purged = registry.purge(now);
    if (purged > 0) getLogger('registry').info(`오래된 세션 ${purged}개를 정리했다`);
    if (options.logDir === null) return;
    const { removed, warnings } = purgeLogs(options.logDir, now, {
      maxAgeSeconds: options.logMaxAgeSeconds,
      keep: options.logFile(),
    });
    if (removed > 0) logger.info(`오래된 로그 ${removed}개를 지웠다`);
    for (const message of warnings) logger.warn(message);
  }, 600_000);
  // 이 타이머가 이벤트 루프를 붙들면 프로세스가 종료되지 않는다.
  purgeTimer.unref();

  return {
    close: async () => {
      shuttingDown = true;
      clearInterval(purgeTimer);

      const closed = Promise.all([
        new Promise<void>((resolve) => mcpServer.close(() => resolve())),
        new Promise<void>((resolve) => adminServer.close(() => resolve())),
      ]);

      // server.close() 는 새 연결만 막을 뿐, 이미 맺힌 연결이 스스로 끝나기를
      // 기다린다 — 느린 리더가 쓰기 버퍼를 막아 두면 그 대기가 무한정
      // 늘어난다. GRACEFUL_SHUTDOWN_MS 안에 자연 종료가 안 되면
      // closeAllConnections() 로 남은 연결을 강제로 끊는다. 라우트 하나가
      // 아니라 여기서 두 서버 모두를 다루는 이유는, 이 함정이
      // /api/logs/stream 뿐 아니라 MCP 쪽 알림용 GET 스트림에도 똑같이
      // 있기 때문이다.
      let timedOut = false;
      const timeout = new Promise<void>((resolve) => {
        setTimeout(() => {
          timedOut = true;
          resolve();
        }, GRACEFUL_SHUTDOWN_MS);
      });
      await Promise.race([closed, timeout]);
      if (timedOut) {
        mcpServer.closeAllConnections();
        adminServer.closeAllConnections();
        await closed;
      }
    },
  };
}

function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.removeListener('error', reject);
      resolve();
    });
  });
}
