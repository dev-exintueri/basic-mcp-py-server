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
 * test_sessions_fragment_has_the_contracted_columns 가 따라온다.
 *
 * **깨면 안 되는 것.** 세션에서 온 값은 반드시 escapeHtml() 을 거쳐 넣는다.
 * 그 값들은 클라이언트가 정한다.
 */

import express from 'express';
import type { Express, Request, Response } from 'express';

import { accessLog } from './access.js';
import { getLogger, type Clock } from './logging.js';
import { Registry, sessionView } from './registry.js';

const registryLogger = getLogger('registry');

// 세션 표를 다시 받아오는 주기(밀리초). 이 폴링 자체가 접근 로그에 한 줄을
// 남기고 그 줄이 다시 로그 패널로 방송되므로, 주기를 짧게 두면 사용자가 보고
// 있는 화면을 자기 소음으로 채운다.
const SESSION_POLL_MS = 30000;

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
}

export function buildAdminApp(options: AdminOptions): Express {
  const { registry, startedAt, clock, mcpEndpoint, runtime } = options;

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
    res.json({
      pid: process.pid,
      runtime,
      uptime_seconds: (now.getTime() - startedAt.getTime()) / 1000,
      mcp_endpoint: mcpEndpoint,
      session_count: views.length,
      sessions: views,
      log_dir: null,
      log_file: null,
    });
  });

  app.get('/fragments/sessions', (_req: Request, res: Response) => {
    res.type('html').send(sessionsHtml());
  });

  app.get('/', (_req: Request, res: Response) => {
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
<p class="note">파일 로깅이 아직 붙지 않았다.</p>
<pre id="log"></pre>
<script>
setInterval(async () => {
  try {
    const html = await (await fetch('/fragments/sessions')).text();
    document.getElementById('sessions').innerHTML = html;
  } catch (e) { /* 서버가 잠깐 없을 수 있다. 다음 주기에 다시 시도한다. */ }
}, ${SESSION_POLL_MS});
</script>
</body>
</html>`);
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
