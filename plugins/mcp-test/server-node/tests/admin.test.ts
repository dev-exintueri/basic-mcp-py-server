import { createServer, type Server } from 'node:http';
import http from 'node:http';
import { EventEmitter, once } from 'node:events';
import { describe, expect, it } from 'vitest';

import { buildAdminApp, waitForWritable } from '../src/admin.js';
import { LogBroadcaster } from '../src/logStream.js';
import { Registry } from '../src/registry.js';

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startServer(
  broadcaster: LogBroadcaster,
  shouldStop: () => boolean,
): Promise<{ server: Server; port: number }> {
  const registry = new Registry(300);
  const app = buildAdminApp({
    registry,
    startedAt: new Date(),
    clock: () => new Date(),
    mcpEndpoint: 'http://127.0.0.1:8765/mcp',
    runtime: 'node',
    broadcaster,
    logFile: () => null,
    shouldStop,
  });
  const server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('포트를 못 받았다');
  return { server, port: address.port };
}

/** 구독자가 실제로 연결될 때까지 기다린다. http.get 의 콜백은 비동기라 그 전에 publish() 하면 씹힌다. */
async function waitForSubscriber(broadcaster: LogBroadcaster): Promise<void> {
  while (broadcaster.subscriberCount < 1) await delay(5);
}

/** 멈춘 리더에게 실제로 커널 쓰기 버퍼가 찰 만큼(res.write() 가 false 를 낼 만큼) 부하를 흘린다. */
async function induceBackpressure(broadcaster: LogBroadcaster, lines: number): Promise<void> {
  const body = 'x'.repeat(400);
  for (let i = 0; i < lines; i++) {
    broadcaster.publish(body);
    await new Promise((resolve) => setImmediate(resolve));
  }
}

// 아래 두 통합 테스트는 admin.ts 의 /api/logs/stream 이 실제 res.write()
// 백프레셔와 종료 신호를 어떻게 경주시키는지, 진짜 http.Server 로 겨냥한다.
// 목(mock) res 를 쓰지 않는 이유는 가짜 res 가 실제 ServerResponse 의 쓰기
// 버퍼/'drain' 이벤트 동작과 갈리면 아무것도 증명하지 못하기 때문이다(리뷰
// 지적).
//
// 부하는 한 줄씩 이벤트 루프에 양보하며 publish() 한다. 한 번의 동기 burst
// 로 몰아 쓰면 Subscriber.push() 의 maxQueue 드롭이 소비자와 무관하게 그
// 자체로 부하를 막아 버려 실제 커널 쓰기 버퍼까지 흘러가는 누적 바이트가
// 몇 KB 로 묶인다 — 그러면 res.write() 가 결코 false 를 돌려주지 않아 이
// 테스트들이 겨냥하는 경로(waitForWritable)를 한 번도 안 밟는다(실측:
// task-11-report.md 의 "첫 시도(실패, 방법론 오류)" 절 참고).
describe('/api/logs/stream 의 백프레셔 경주 (통합, 진짜 http.Server)', () => {
  it('멈춘 리더에서도 shouldStop() 이 true 가 되면 대기 중에 빠르게 끝난다', async () => {
    // waitForWritable() 이 `once(res, 'drain')` 을 shouldAbort() 확인 없이
    // 무한정 기다리게 바뀌면(1초 폴링용 AbortController 를 지우면) 이
    // 테스트는 타임아웃으로 실패한다 — 실제로 지워서 확인했다
    // (task-11-report.md 참고).
    //
    // 완료 신호로 클라이언트가 보는 res 의 'close'/'end' 를 안 쓴다. 리더가
    // 계속 안 읽으면 res.end() 의 콜백(플러시 완료 시점)이 영원히 안 올 수
    // 있어(그게 Important 1 이 app.ts 의 close() 에 상한을 둔 이유다), 그
    // 신호에 기대면 이 테스트가 admin.ts 단독으로는 증명할 수 없는 것을
    // 증명하려는 셈이 된다. 대신 finally 블록이 res.end() 를 부르기 **전에**
    // 이미 실행하는 broadcaster.unsubscribe() 를 신호로 쓴다 — while 루프가
    // shouldStop() 을 보고 빠져나오는 순간 바로 도는 호출이다.
    const broadcaster = new LogBroadcaster();
    let stopped = false;
    const { server, port } = await startServer(broadcaster, () => stopped);

    const req = http.get(`http://127.0.0.1:${port}/api/logs/stream`, (res) => {
      res.pause(); // 절대 읽지 않는다 — 멈춘 리더를 흉내낸다
    });

    await waitForSubscriber(broadcaster);
    await induceBackpressure(broadcaster, 3000); // ~1.3MB, 커널 버퍼를 채우기에 충분하다
    expect(broadcaster.subscriberCount).toBe(1); // 아직 대기 중이어야 정상이다

    const started = Date.now();
    stopped = true; // close() 가 shuttingDown 을 true 로 만드는 것과 같다
    while (broadcaster.subscriberCount > 0) await delay(20);
    const elapsed = Date.now() - started;

    // waitForWritable() 의 1초 폴링 덕에 몇 초 안에 끝나야 한다.
    expect(elapsed).toBeLessThan(3000);

    req.destroy();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }, 20000);

  it('멈춘 리더에서 클라이언트가 연결을 끊으면 대기 중이던 백프레셔가 빠르게 풀린다', async () => {
    // 위 테스트가 shouldStop() 경로를 겨냥한다면, 이건 req.on('close') 로
    // 세팅되는 `closed` 경로를 겨냥한다 — waitForWritable() 에 넘기는
    // shouldAbort 콜백은 `() => closed || shouldStop()` 이다.
    const broadcaster = new LogBroadcaster();
    const { server, port } = await startServer(broadcaster, () => false);

    const request = http.get(`http://127.0.0.1:${port}/api/logs/stream`);
    const gotResponse = new Promise<void>((resolve) => request.on('response', () => resolve()));
    await gotResponse;

    await waitForSubscriber(broadcaster);
    await induceBackpressure(broadcaster, 3000);

    const started = Date.now();
    request.destroy(); // 브라우저 탭을 닫는 것과 같다
    // 구독자가 실제로 정리됐는지(=SSE 핸들러의 finally 가 돌았는지)로
    // "빠르게 풀렸다"를 확인한다.
    while (broadcaster.subscriberCount > 0) await delay(20);
    const elapsed = Date.now() - started;

    expect(elapsed).toBeLessThan(3000);

    await new Promise<void>((resolve) => server.close(() => resolve()));
  }, 20000);
});

// 아래는 waitForWritable() 자체를 직접 겨냥한다. 평범한 EventEmitter 를
// `res` 자리에 넘긴다 — waitForWritable() 은 `res` 를 오직
// `once(res, 'drain', { signal })` 로만 쓰므로(admin.ts 참고), 이는 진짜
// ServerResponse 를 넘기는 것과 노드 내부적으로 같은 events.once() 경로를
// 탄다. "목이 실제 동작과 갈리면 아무것도 증명 못 한다"는 우려가 적용되지
// 않는 경우다.
describe('waitForWritable', () => {
  it('drain 이벤트가 오면 1초 폴링을 기다리지 않고 바로 반환한다', async () => {
    const emitter = new EventEmitter();
    const started = Date.now();
    const promise = waitForWritable(emitter, () => false);
    await delay(50);
    emitter.emit('drain');
    await promise;
    expect(Date.now() - started).toBeLessThan(500);
  });

  it('drain 이 안 와도 shouldAbort() 가 참이 되면 1초 안팎으로 반환한다', async () => {
    const emitter = new EventEmitter();
    let stop = false;
    const started = Date.now();
    const promise = waitForWritable(emitter, () => stop);
    await delay(50);
    stop = true;
    await promise;
    const elapsed = Date.now() - started;
    // 1초 폴링 주기 하나 안에 들어와야 한다. 이 상한을 지우면(그냥
    // once(res, 'drain') 만 기다리는 코드로 되돌리면) 이 테스트는 절대
    // 끝나지 않고 vitest 기본 타임아웃으로 FAIL 한다.
    expect(elapsed).toBeLessThan(2000);
  });

  it('여러 번 abort 를 거쳐도 emitter 에 drain 리스너가 남지 않는다', async () => {
    // shouldAbort() 를 계속 false 로 둬 waitForWritable() 의 내부 1초
    // 타임아웃이 몇 차례 실제로 발동하게 만든다 — 그때마다
    // AbortController 가 once() 의 리스너를 지우는지 본다. 지우지 않으면
    // (예: 매번 새 리스너만 추가하고 예전 것을 안 지우면) 이 개수가
    // 사이클마다 계속 늘어난다.
    const emitter = new EventEmitter();
    let stop = false;
    const promise = waitForWritable(emitter, () => stop);

    // 1.05초씩 세 번 재워 내부 1초 타임아웃이 최소 두세 번은 돌게 한다.
    await delay(1050);
    expect(emitter.listenerCount('drain')).toBeLessThanOrEqual(1);
    await delay(1050);
    expect(emitter.listenerCount('drain')).toBeLessThanOrEqual(1);

    stop = true;
    await promise;
    expect(emitter.listenerCount('drain')).toBe(0);
  }, 10000);

  it('once() 로 등록한 리스너와의 경주에서 emitter 가 다른 목적에도 재사용 가능하다', async () => {
    // 참고용 성질: waitForWritable() 이 끝난 뒤 emitter 에 관계없는 리스너를
    // 더 붙여도 예전 'drain' 리스너와 충돌하지 않는다(리스너가 정리됐다는
    // 방증이다). node:events 의 once() 를 직접 대조군으로 써서, 우리
    // waitForWritable() 이 그 계약을 그대로 따르는지 확인한다.
    const emitter = new EventEmitter();
    await Promise.all([waitForWritable(emitter, () => true), delay(10)]);
    expect(emitter.listenerCount('drain')).toBe(0);

    // 대조군: node:events 의 once() 자체도 이벤트가 온 뒤엔 리스너를 남기지 않는다.
    const control = new EventEmitter();
    const p = once(control, 'drain');
    control.emit('drain');
    await p;
    expect(control.listenerCount('drain')).toBe(0);
  });
});
