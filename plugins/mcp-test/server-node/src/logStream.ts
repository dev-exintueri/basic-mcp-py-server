/**
 * 로그 줄을 SSE 구독자에게 fan-out 한다.
 *
 * 파일을 다시 읽지 않는다. 로거의 sink 에서 바로 밀기 때문에 파일 회전은
 * 스트림과 무관하고, 파일 로깅이 꺼져 있어도 스트림은 동작한다.
 *
 * ## 응용할 때
 *
 * 포크해도 대개 그대로 둔다. 고친다면 maxQueue 정도다.
 *
 * **깨면 안 되는 것.** 큐가 가득 차면 오래된 것부터 버린다. 느린 브라우저가
 * 서버를 세우면 안 된다. 그리고 publish() 는 어떤 경우에도 예외를 내지
 * 않는다 — 여기서 터지면 이 기능의 존재 이유인 크래시 줄이 사라진다.
 */

export class Subscriber {
  readonly queue: string[] = [];
  private waiter: (() => void) | null = null;

  push(line: string, maxQueue: number): void {
    if (this.queue.length >= maxQueue) this.queue.shift();
    this.queue.push(line);
    const waiter = this.waiter;
    this.waiter = null;
    waiter?.();
  }

  /** 줄이 생길 때까지 기다린다. timeoutMs 안에 없으면 빈 배열. */
  async drain(timeoutMs: number): Promise<string[]> {
    if (this.queue.length > 0) return this.queue.splice(0);
    await new Promise<void>((resolve) => {
      this.waiter = resolve;
      setTimeout(() => {
        if (this.waiter === resolve) {
          this.waiter = null;
          resolve();
        }
      }, timeoutMs);
    });
    return this.queue.splice(0);
  }
}

export class LogBroadcaster {
  private subscribers = new Set<Subscriber>();

  constructor(private maxQueue = 1000) {}

  get subscriberCount(): number {
    return this.subscribers.size;
  }

  subscribe(): Subscriber {
    const subscriber = new Subscriber();
    this.subscribers.add(subscriber);
    return subscriber;
  }

  unsubscribe(subscriber: Subscriber): void {
    this.subscribers.delete(subscriber);
  }

  publish(line: string): void {
    for (const subscriber of this.subscribers) {
      try {
        subscriber.push(line, this.maxQueue);
      } catch {
        // 한 구독자가 실패해도 나머지에는 민다.
      }
    }
  }
}
