import { describe, expect, it } from 'vitest';
import { LogBroadcaster } from '../src/logStream.js';

// 파이썬 tests/test_logstream.py 가 고정하는 동작을 옮긴다. 파이썬 쪽의
// "루프가 없다/닫혔다" 계열 3개(test_publish_without_a_loop_does_not_raise 등)는
// asyncio 이벤트 루프 바인딩이라는 파이썬 전용 개념이라 여기엔 대응이 없다 —
// 노드의 LogBroadcaster 는 이벤트 루프를 따로 바인딩하지 않고 항상 동기로
// push() 한다. 나머지 구독 관련 동작은 그대로 옮긴다.

describe('LogBroadcaster', () => {
  it('구독자가 없어도 publish() 는 예외를 내지 않는다', () => {
    expect(() => new LogBroadcaster().publish('구독자 없음')).not.toThrow();
  });

  it('구독자는 publish() 된 줄을 받는다', async () => {
    const broadcaster = new LogBroadcaster();
    const subscriber = broadcaster.subscribe();

    broadcaster.publish('첫 줄');

    expect(await subscriber.drain(1000)).toEqual(['첫 줄']);
  });

  it('drain() 은 대기 중에 publish() 되면 타임아웃을 기다리지 않고 즉시 깨어난다', async () => {
    // Subscriber.push() 의 `waiter?.()` 호출을 지우면 이 테스트는 5000ms
    // 타임아웃을 그대로 다 기다린 뒤에야 통과한다 — 아래 500ms 미만
    // 단언이 그 차이를 잡는다.
    const broadcaster = new LogBroadcaster();
    const subscriber = broadcaster.subscribe();

    const started = Date.now();
    const drainPromise = subscriber.drain(5000);
    // drain() 이 먼저 대기 상태(waiter 등록)로 들어가게 한 뒤에 publish() 한다.
    await new Promise((resolve) => setTimeout(resolve, 20));
    broadcaster.publish('늦게 온 줄');

    const lines = await drainPromise;
    const elapsed = Date.now() - started;

    expect(lines).toEqual(['늦게 온 줄']);
    expect(elapsed).toBeLessThan(500);
  });

  it('unsubscribe() 뒤에는 subscriberCount 가 준다', () => {
    const broadcaster = new LogBroadcaster();
    const subscriber = broadcaster.subscribe();

    expect(broadcaster.subscriberCount).toBe(1);
    broadcaster.unsubscribe(subscriber);
    expect(broadcaster.subscriberCount).toBe(0);
  });

  it('unsubscribe() 는 멱등이다 — 두 번 불러도 던지지 않는다', () => {
    const broadcaster = new LogBroadcaster();
    const subscriber = broadcaster.subscribe();

    broadcaster.unsubscribe(subscriber);
    expect(() => broadcaster.unsubscribe(subscriber)).not.toThrow();
  });

  it('unsubscribe() 뒤에는 더 이상 줄을 받지 않는다', () => {
    // admin.ts 의 /api/logs/stream 이 연결 종료 시 unsubscribe() 를 안 부르면
    // 관리 페이지를 열 때마다 Subscriber 가 영구히 쌓인다. 이 단언은
    // LogBroadcaster.unsubscribe() 자체가 실제로 구독을 끊는지 고정한다 —
    // publish() 의 `for (const subscriber of this.subscribers)` 순회에서
    // 빠지는지를 본다.
    const broadcaster = new LogBroadcaster();
    const subscriber = broadcaster.subscribe();

    broadcaster.unsubscribe(subscriber);
    broadcaster.publish('구독 해제 후');

    expect(subscriber.queue).toEqual([]);
  });

  it('큐가 가득 차면 오래된 것부터 버린다', () => {
    // Subscriber.push() 의 `if (this.queue.length >= maxQueue) this.queue.shift();`
    // 를 지우면 이 단언이 ['line0', 'line1', ..., 'line4'] 를 보게 되어 깨진다.
    const broadcaster = new LogBroadcaster(2);
    const subscriber = broadcaster.subscribe();

    for (let i = 0; i < 5; i++) broadcaster.publish(`line${i}`);

    expect(subscriber.queue).toEqual(['line3', 'line4']);
  });

  it('publish() 는 서식화된 문자열을 그대로 전달한다', async () => {
    // logging.ts 의 getLogger() 가 formatLine() 으로 이미 조립한 완성 문자열을
    // sink 에 넘긴다 — LogBroadcaster 는 그것을 재조립하지 않고 그대로 큐에
    // 넣는다(파이썬의 BroadcastHandler 가 LogRecord 가 아니라 포맷된 문자열을
    // 넘기는 것과 같은 이유 — 나중에 다른 시점에 다시 조립하면 파일과
    // 화면의 내용이 갈릴 수 있다).
    const broadcaster = new LogBroadcaster();
    const subscriber = broadcaster.subscribe();
    const line = '2026-01-01T00:00:00Z INFO  app      PREFIX 값 42';

    broadcaster.publish(line);

    const received = await subscriber.drain(1000);
    expect(received).toEqual([line]);
    expect(typeof received[0]).toBe('string');
  });

  it('여러 구독자가 각각 같은 줄을 받는다 (fan-out)', async () => {
    const broadcaster = new LogBroadcaster();
    const s1 = broadcaster.subscribe();
    const s2 = broadcaster.subscribe();
    const s3 = broadcaster.subscribe();

    broadcaster.publish('공중파');

    expect(await s1.drain(1000)).toEqual(['공중파']);
    expect(await s2.drain(1000)).toEqual(['공중파']);
    expect(await s3.drain(1000)).toEqual(['공중파']);
  });
});
