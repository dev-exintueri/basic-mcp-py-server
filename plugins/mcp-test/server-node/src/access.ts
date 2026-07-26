/**
 * 접근 로그 미들웨어. 요청 하나당 줄 하나, 거부된 요청도 포함한다.
 *
 * ## 응용할 때
 *
 * 포크해도 대개 그대로 둔다. 고친다면 어떤 필드를 남기는지 정도다.
 *
 * **깨면 안 되는 것.**
 *
 * - 이 미들웨어를 authMiddleware 보다 **먼저** 등록한다. express 에서
 *   등록 순서가 곧 바깥/안쪽이다. 뒤집으면 401/403 으로 거부된 요청이
 *   로그에 남지 않는다.
 * - 로그는 응답이 **시작**될 때 남긴다. res.on('finish') 로 옮기면
 *   /api/logs/stream 같은 SSE 연결은 브라우저 탭이 닫힐 때까지 아무 줄도
 *   남기지 않는다. 그래서 writeHead 를 감싼다. 그 대신 SSE 연결은 열리는
 *   순간 dur_ms 가 0에 가까운 줄 하나를 남기고 갱신되지 않는다. 의도한
 *   동작이다.
 * - 캐리지 리턴과 줄바꿈 이스케이프는 조립이 끝난 한 줄에 한 번 건다.
 *   필드마다 거는 방식으로 바꾸면 새 필드가 생길 때 조용히 샌다.
 */

import type { NextFunction, Request, RequestHandler, Response } from 'express';

import { maskSecret } from './auth.js';
import { getLogger } from './logging.js';

const logger = getLogger('http');

export function accessLog(): RequestHandler {
  return (req: Request, res: Response, next: NextFunction): void => {
    const started = process.hrtime.bigint();
    let logged = false;

    const write = (status: number): void => {
      if (logged) return;
      logged = true;
      const durationMs = Number(process.hrtime.bigint() - started) / 1e6;

      const parts = [req.method, req.originalUrl, String(status), `dur_ms=${durationMs.toFixed(0)}`];
      const info = req.mcpTestAuth;
      if (info?.instance) parts.push(`instance=${info.instance}`);
      if (info?.subject) parts.push(`subject=${maskSecret(info.subject)}`);
      if (info?.reason) parts.push(`reason=${info.reason}`);

      // 줄바꿈을 이스케이프한 뒤에 넘긴다. 경로와 연결 ID 는 클라이언트가
      // 정하는 값이고 마스킹도 걸리지 않는다. 날것으로 두면 요청 하나로
      // 진짜와 구별되지 않는 로그 줄을 만들어 넣을 수 있고(위조), 캐리지
      // 리턴은 그보다 나쁘다 — SSE 프레이밍은 줄바꿈만 나누므로 캐리지
      // 리턴이 든 줄은 관리 화면에서 통째로 사라진다(은폐). 토큰 없이도
      // 되는 일이라 401 로 거부된 요청에도 해당한다.
      const line = parts.join(' ').replace(/\r/g, '\\r').replace(/\n/g, '\\n');
      if (status >= 400) logger.warn(line);
      else logger.info(line);
    };

    const originalWriteHead = res.writeHead.bind(res);
    // 첫 바이트에서 남기기 위해 writeHead 를 감싼다. 자세한 이유는 위
    // 모듈 주석에 있다.
    res.writeHead = function patched(this: Response, ...args: unknown[]) {
      write(res.statusCode);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (originalWriteHead as any)(...args);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;

    // 응답을 한 번도 시작하지 못하고 끊긴 경우다. 상태는 없지만 요청이
    // 있었다는 사실은 남겨야 한다.
    res.on('close', () => write(0));

    next();
  };
}
