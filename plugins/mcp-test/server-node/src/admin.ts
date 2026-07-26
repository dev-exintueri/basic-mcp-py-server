/**
 * 관리 포트 앱. 127.0.0.1 에만 바인딩되며 인증하지 않는다.
 *
 * 인증이 없는 이유는 브라우저가 URL 을 여는 것만으로 Authorization 헤더를
 * 붙일 수 없기 때문이다.
 *
 * 그 대가를 정확히 적어 둔다. 루프백 바인딩은 **다른 기계**를 막을 뿐이다.
 * 이 앱이 상대하려는 클라이언트가 같은 기계의 브라우저이므로, 사용자가 연
 * 아무 웹 페이지나 이 포트에 닿을 수 있다. Origin 도 Host 도 검사하지
 * 않으므로, 그 페이지가 폼을 자동 제출해 살아 있는 세션을 차단할 수 있고
 * DNS 리바인딩으로 /api/status 를 읽을 수도 있다. 로컬 테스트 도구라서
 * 막지 않기로 한 것이다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** HTML 템플릿과 라우트 목록. 폴링 주기도 여기 있다.
 *
 * **함께 바꿔야 하는 것.** 표의 열을 바꾸면 conformance 스위트의
 * test_sessions_fragment_has_the_contracted_columns 가 따라온다. 로그 줄
 * 형식을 바꾸면 logging.ts 의 formatLine() 과 logPaths.ts 의 tailLines() 를
 * 함께 본다.
 *
 * **깨면 안 되는 것.**
 * - 세션에서 온 값은 반드시 escapeHtml() 을 거쳐 넣는다. 그 값들은
 *   클라이언트가 정한다.
 * - `/api/status` 는 정확히 8개 키를 낸다. conformance 스위트의
 *   test_status_has_the_contracted_keys 가 `set(payload)` 를 그 여덟 개와
 *   비교한다. 필드를 늘리거나 줄이면 실패한다.
 * - `/api/logs/stream` 의 while 루프는 `shouldStop()` 이 참이 되면 스스로
 *   끝난다. 지우면 SSE 연결이 서버 종료를 막아, close() 가 열린 응답이
 *   끝나기를 무한정 기다리게 된다.
 * - `/api/logs/stream` 이 끝날 때 `res.end()` 콜백 안에서 소켓을 직접
 *   파괴한다. SSE 연결은 keep-alive 로 재사용될 일이 없는데, 파괴하지
 *   않으면 노드 기본 `keepAliveTimeout`(5초)만큼 소켓이 살아남아 서버
 *   종료가 그만큼 늦어진다 — 실측(리뷰): 관리 페이지를 열어 둔 채
 *   SIGTERM 을 보내면 종료가 7초 넘게 걸렸다(파이썬은 0.38초). 파이썬은
 *   `timeout_graceful_shutdown` 으로 상한을 두지만, 노드는 이 연결이 다시
 *   쓰일 일이 없으므로 아예 즉시 닫는 쪽을 골랐다.
 * - `res.write()` 가 `false` 를 돌려주면(쓰기 버퍼가 참) `drain` 이벤트를
 *   기다린 뒤에 다음 줄을 쓴다. 이 대기를 건너뛰면 `LogBroadcaster` 의
 *   `maxQueue` 상한이 실전에서 결코 닿지 않는다 — sink 의 publish() 가
 *   동기 호출이라, 이 라우트가 매 줄을 즉시 res.write() 해 버리면
 *   Subscriber 의 큐가 늘 1개 근처에 머물고 "오래된 것부터 버린다"는
 *   불변식이 죽은 코드가 된다(리뷰 Important 3). 다만 이 대기는
 *   `shouldStop()`/연결 종료와 경주해야 한다 — 그러지 않으면 멈춘
 *   리더가 서버 종료 자체를 막는다.
 */

import express from 'express';
import type { Express, Request, Response } from 'express';
import { once } from 'node:events';
import { dirname } from 'node:path';

import { accessLog } from './access.js';
import { getLogger, type Clock } from './logging.js';
import { tailLines } from './logPaths.js';
import type { LogBroadcaster } from './logStream.js';
import { Registry, sessionView } from './registry.js';

const registryLogger = getLogger('registry');

// 세션 표를 다시 받아오는 주기(밀리초). 이 폴링 자체가 접근 로그에 한 줄을
// 남기고 그 줄이 다시 로그 패널로 방송되므로, 주기를 짧게 두면 사용자가 보고
// 있는 화면을 자기 소음으로 채운다.
const SESSION_POLL_MS = 30000;

/**
 * res.write() 가 false(쓰기 버퍼 참)를 돌려줬을 때 drain 을 기다린다.
 *
 * once(res, 'drain') 을 그냥 기다리면, 클라이언트가 영영 안 읽을 때(탭을
 * 열어만 두고 최소화한 브라우저 등) 서버 종료 신호가 와도 이 대기가 풀리지
 * 않는다. 그래서 1초마다 깨어나 `shouldAbort()` 를 다시 보고, 참이면 drain
 * 을 기다리지 않고 그냥 돌아간다 — 호출부가 그 뒤 바깥 while 루프에서
 * closed/shouldStop() 을 보고 스스로 끝난다.
 */
async function waitForWritable(res: Response, shouldAbort: () => boolean): Promise<void> {
  while (!shouldAbort()) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1000);
    try {
      await once(res, 'drain', { signal: controller.signal });
      return;
    } catch {
      // 1초 안에 drain 이 안 왔다. shouldAbort() 를 다시 보러 루프 상단으로.
    } finally {
      clearTimeout(timer);
    }
  }
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

export interface AdminOptions {
  registry: Registry;
  startedAt: Date;
  clock: Clock;
  mcpEndpoint: string;
  runtime: string;
  broadcaster: LogBroadcaster | null;
  logFile: () => string | null;
  shouldStop: () => boolean;
}

export function buildAdminApp(options: AdminOptions): Express {
  const { registry, startedAt, clock, mcpEndpoint, runtime, broadcaster, logFile, shouldStop } =
    options;

  const snapshot = (): { now: Date; views: Record<string, unknown>[] } => {
    const now = clock();
    return { now, views: registry.all().map((r) => sessionView(r, registry, now)) };
  };

  const sessionsHtml = (): string => {
    const { now, views } = snapshot();
    const rows = views
      .map((v) => {
        const classes = [v.stale ? 'stale' : '', v.blocked ? 'blocked' : '']
          .filter(Boolean)
          .join(' ');
        const action = v.blocked ? 'unblock' : 'block';
        const actionLabel = v.blocked ? '차단 해제' : '차단';
        const id = escapeHtml(String(v.instance_id));
        return `<tr class="${classes}">
<td>${id}</td><td>${escapeHtml(String(v.subject))}</td>
<td>${escapeHtml(String(v.project))}</td><td>${escapeHtml(String(v.label))}</td>
<td>${escapeHtml(String(v.connected_at))}</td><td>${escapeHtml(String(v.last_seen))}</td>
<td>${String(v.call_count)}</td>
<td><form method="post" action="/api/sessions/${id}/${action}">
<button type="submit">${actionLabel}</button></form></td>
</tr>`;
      })
      .join('');

    const uptime = ((now.getTime() - startedAt.getTime()) / 1000).toFixed(0);
    return `<p>pid ${process.pid} · uptime ${uptime}s · MCP ${escapeHtml(mcpEndpoint)} · 세션 ${views.length}개</p>
<p class="note">차단하면 그 세션은 403을 받고, Claude Code가 headersHelper를
다시 실행해 <b>새 연결 ID로 되살아난다.</b> 레코드가 사라지고 새 줄이
나타나는 것이 정상이다.</p>
<table>
<tr><th>연결 ID</th><th>subject</th><th>project</th><th>label</th>
<th>연결 시각</th><th>마지막 호출</th><th>호출</th><th></th></tr>
${rows}
</table>`;
  };

  const app = express();
  app.use(accessLog());
  app.use(express.urlencoded({ extended: false }));

  app.get('/api/status', (_req: Request, res: Response) => {
    const { now, views } = snapshot();
    const path = logFile();
    res.json({
      pid: process.pid,
      runtime,
      uptime_seconds: (now.getTime() - startedAt.getTime()) / 1000,
      mcp_endpoint: mcpEndpoint,
      session_count: views.length,
      sessions: views,
      log_dir: path === null ? null : dirname(path),
      log_file: path,
    });
  });

  app.get('/fragments/sessions', (_req: Request, res: Response) => {
    res.type('html').send(sessionsHtml());
  });

  app.get('/', (_req: Request, res: Response) => {
    const path = logFile();
    const note = path === null
      ? '파일 로깅이 꺼져 있다. 아래는 이 연결 이후의 로그만 보여준다.'
      : `${escapeHtml(path)} · 최근 200줄`;
    const backfill = path === null ? '' : escapeHtml(tailLines(path).join('\n'));
    res.type('html').send(`<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>MCP 테스트 서버</title>
<style>
body { font-family: ui-monospace, monospace; margin: 2rem; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; }
.stale { color: #888; }
.blocked { background: #fee; }
.note { color: #666; font-size: .9rem; }
#log { background: #111; color: #ddd; padding: .8rem; height: 24rem;
       overflow-y: scroll; white-space: pre-wrap; margin-top: .5rem; }
</style>
</head>
<body>
<h1>MCP 테스트 서버</h1>
<div id="sessions">${sessionsHtml()}</div>
<h2>로그</h2>
<p class="note">${note}</p>
<pre id="log">${backfill}</pre>
<script>
setInterval(async () => {
  try {
    const html = await (await fetch('/fragments/sessions')).text();
    document.getElementById('sessions').innerHTML = html;
  } catch (e) { /* 서버가 잠깐 없을 수 있다. 다음 주기에 다시 시도한다. */ }
}, ${SESSION_POLL_MS});

const box = document.getElementById('log');
box.scrollTop = box.scrollHeight;
new EventSource('/api/logs/stream').onmessage = (event) => {
  // 맨 아래를 보고 있을 때만 따라간다. 위로 올려 읽는 중이면 방해하지 않는다.
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent += event.data + '\\n';
  if (atBottom) box.scrollTop = box.scrollHeight;
};
</script>
</body>
</html>`);
  });

  app.get('/api/logs/stream', async (req: Request, res: Response) => {
    if (broadcaster === null) {
      res.status(503).json({ error: '로그 스트림이 꺼져 있다' });
      return;
    }
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    // writeHead() 는 헤더를 소켓에 바로 내보내지 않는다 — 노드는 첫 write()
    // 나 end() 가 있을 때까지 미룬다. 이 라우트는 실제 로그 줄이 생길 때까지
    // 아무것도 쓰지 않을 수 있으므로, flushHeaders() 없이는 클라이언트가
    // 응답 상태 코드조차 받지 못한 채 오래 멈춘다(파이썬 StreamingResponse
    // 는 ASGI http.response.start 메시지를 시작하자마자 보낸다). 실측:
    // 이 줄이 없으면 conformance 의 test_log_stream_emits_new_lines 와
    // test_access_log_records_the_sse_connection_immediately 가 ReadTimeout
    // 으로 실패한다.
    res.flushHeaders();

    const subscriber = broadcaster.subscribe();
    let closed = false;
    req.on('close', () => {
      closed = true;
    });

    try {
      let idle = 0;
      while (!closed && !shouldStop()) {
        // 1초씩 깨어나는 이유는 하트비트가 아니라 종료다. 15초를 통째로
        // 기다리면 그 사이에 시작된 종료를 최대 15초 동안 못 본다.
        const lines = await subscriber.drain(1000);
        if (lines.length === 0) {
          idle += 1;
          if (idle >= 15) {
            idle = 0;
            res.write(': ping\n\n'); // 유휴 연결이 끊기지 않게 하는 주석 하트비트
          }
          continue;
        }
        idle = 0;
        for (const line of lines) {
          if (closed || shouldStop()) break;
          // 트레이스백은 여러 줄이다. 줄마다 data: 를 붙이지 않으면 SSE
          // 프레이밍이 깨진다.
          const payload = line.split('\n').map((part) => `data: ${part}\n`).join('');
          // res.write() 가 false 를 돌려주면 쓰기 버퍼가 찼다는 뜻이다 —
          // 클라이언트가 못 따라가고 있다. 여기서 기다리지 않고 계속
          // 쓰면(버퍼링만 늘어난다) LogBroadcaster 의 maxQueue 상한이 결코
          // 문제 되지 않는다. 자세한 이유는 위 모듈 주석에 있다.
          if (!res.write(payload + '\n')) {
            await waitForWritable(res, () => closed || shouldStop());
          }
        }
      }
    } finally {
      broadcaster.unsubscribe(subscriber);
      // res.end() 뒤에는 res.socket 이 null 이 될 수 있다 — 노드가 keep-alive
      // 재사용을 위해 소켓을 응답 객체에서 떼어내기 때문이다(detachSocket).
      // 그래서 떼이기 전에 참조를 미리 잡아 둔다. 응답이 실제로 플러시된
      // 뒤(콜백 시점)에 그 소켓을 파괴한다 — SSE 연결은 keep-alive 로
      // 재사용되지 않으므로, 파괴하지 않고 두면 노드 기본
      // keepAliveTimeout(5초) 만큼 그대로 눕는다. 자세한 이유는 위 모듈
      // 주석에 있다.
      const socket = res.socket;
      res.end(() => {
        if (socket && !socket.destroyed) socket.destroy();
      });
    }
  });

  /** block 과 unblock 라우트를 같은 코드로 만든다. */
  const toggle = (action: 'block' | 'unblock') => (req: Request, res: Response): void => {
    const instanceId = req.params.instanceId as string;
    const changed = action === 'block' ? registry.block(instanceId) : registry.unblock(instanceId);
    if (!changed) {
      res.status(404).json({ error: `알 수 없는 연결 ID: ${instanceId}` });
      return;
    }
    registryLogger.info(`${action} instance=${instanceId}`);
    if ((req.headers['accept'] ?? '').includes('text/html')) {
      res.redirect(303, '/');
      return;
    }
    res.json({ instance_id: instanceId, action });
  };

  app.post('/api/sessions/:instanceId/block', toggle('block'));
  app.post('/api/sessions/:instanceId/unblock', toggle('unblock'));

  return app;
}
