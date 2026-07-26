import { createServer } from 'node:http';
import net from 'node:net';
import { describe, expect, it } from 'vitest';

import { isLoopback, serve } from '../src/app.js';
import { LogBroadcaster } from '../src/logStream.js';

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

/** OS 가 골라 주는 빈 포트를 하나 받는다. serve() 는 포트 0(임의 배정)을 못 받으므로 미리 정해야 한다. */
function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const probe = createServer();
    probe.listen(0, '127.0.0.1', () => {
      const address = probe.address();
      const port = address !== null && typeof address === 'object' ? address.port : 0;
      probe.close(() => resolve(port));
    });
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 부분 요청을 보낸 뒤, 서버가 그걸 실제로 받아들여 "진행 중"인 요청으로
 * 등록할 시간을 준다. 그냥 sleep 이 아니다 — 그 대기 동안 소켓이 응답을
 * 받거나 스스로 닫히면(이 테스트가 세운 전제, "요청이 안 끝난 채 남아
 * 있다" 가 깨졌다는 뜻이다) 조용히 넘어가지 않고 그 자체로 실패시킨다.
 * 실측: write() 직후 대기 없이 바로 close() 를 부르면(서버가 아직 헤더를
 * 다 못 받아들인 시점), close() 가 13ms 만에 끝나 버려 이 테스트가 아무것도
 * 증명하지 못했다 — 그 재발을 이 함수가 잡는다.
 */
async function waitForRequestToBeInFlight(socket: net.Socket, ms: number): Promise<void> {
  let settled = false;
  const unexpected = new Promise<never>((_resolve, reject) => {
    socket.once('data', (chunk: Buffer) => {
      if (settled) return;
      reject(new Error(`예상 밖의 응답을 받았다(요청이 이미 끝났다는 뜻): ${chunk.toString('utf8').slice(0, 200)}`));
    });
    socket.once('close', () => {
      if (settled) return;
      reject(new Error('연결이 예상보다 일찍 닫혔다 — "요청이 안 끝난 채 남아 있다"는 전제가 깨졌다'));
    });
  });
  await Promise.race([delay(ms), unexpected]);
  settled = true;
}

describe('serve() 의 close() — 종료 상한', () => {
  // MCP 리스너에 "끝나지 않는 요청"을 하나 걸어 둔다. Content-Length 를
  // 실제로 보낸 바이트보다 크게 선언하고 나머지를 영원히 안 보낸다 —
  // express.json() 이 본문 스트림의 'end' 를 기다리므로 이 요청은 응답도,
  // 연결 종료도 스스로 하지 않는다. server.close() 는 이런 연결이 남아
  // 있으면 콜백이 영원히 안 오므로, 이 시나리오가 app.ts 의 close() 가
  // 상한(GRACEFUL_SHUTDOWN_MS=3000)을 실제로 지키는지 결정적으로 겨냥한다.
  //
  // 4.8MB 짜리 하네스(task-11-report.md 의 라운드 2)와 달리 몇 바이트만
  // 있으면 된다 — 볼륨이 아니라 "완결되지 않은 요청 하나"가 핵심이다.
  it('MCP 리스너에 완결되지 않은 요청이 걸려 있어도 4초 안에 끝난다', async () => {
    const port = await freePort();
    const adminPort = await freePort();
    const broadcaster = new LogBroadcaster();

    const handle = await serve({
      host: '127.0.0.1',
      port,
      adminPort,
      staleAfter: 300,
      clock: () => new Date(),
      broadcaster,
      logDir: null,
      logFile: () => null,
      logMaxAgeSeconds: 3 * 86400,
    });

    const socket = net.connect(port, '127.0.0.1');
    await new Promise<void>((resolve, reject) => {
      socket.once('connect', resolve);
      socket.once('error', reject);
    });
    // Content-Length: 100 이라고 선언하고 10바이트만 보낸다. 나머지 90은
    // 영원히 안 온다 — 서버는 본문을 다 받을 때까지 이 요청을 못 끝낸다.
    // write() 의 콜백으로 로컬 커널이 바이트를 받아들인 시점을 명시적으로
    // 기다린다(그냥 fire-and-forget 으로 두지 않는다).
    await new Promise<void>((resolve, reject) => {
      socket.write(
        'POST /mcp HTTP/1.1\r\n' +
          'Host: 127.0.0.1\r\n' +
          'Content-Type: application/json\r\n' +
          'Content-Length: 100\r\n' +
          'Connection: keep-alive\r\n' +
          '\r\n' +
          '{"partial"',
        (err) => (err ? reject(err) : resolve()),
      );
    });

    // 같은 머신 안에서 서버가 그 바이트를 실제로 파싱해 "진행 중"인 요청으로
    // 등록할 시간을 준다.
    await waitForRequestToBeInFlight(socket, 200);

    try {
      const started = Date.now();
      await handle.close();
      const elapsed = Date.now() - started;

      // GRACEFUL_SHUTDOWN_MS(3000ms) 상한에 여유를 조금 둔 것뿐이다. 이
      // 상한 블록(app.ts 의 closeAllConnections() 호출)을 지우면 이 완결
      // 안 된 요청이 close() 를 영원히 막아 이 단언이 실패한다 — vitest
      // 테스트 타임아웃(10000ms, 아래 세 번째 인자)으로 FAIL 한다.
      expect(elapsed).toBeLessThan(4000);
    } finally {
      socket.destroy();
    }
  }, 10000);
});
