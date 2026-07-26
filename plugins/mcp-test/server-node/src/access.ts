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
 *
 * **이 이스케이프는 노드에서 스위트로 검증할 수 없다 — 파이썬 쪽에서는
 * 발동하고 테스트된다.** req.originalUrl 은 퍼센트 인코딩된 날것이라
 * `%0d%0a` 를 보내도 실제 캐리지 리턴이 안 들어오고, 그 앞서 노드 HTTP
 * 파서 자체가 헤더 값의 CR/LF 를 거부한다 — 위조를 시도하는 요청이
 * 서버에 도달하기도 전에 걸린다. 파이썬은 ASGI `scope["path"]` 가 퍼센트
 * 디코딩된 값이라 실제 CR 을 받고, 이 줄이 그것을 `\r` 로 이스케이프해
 * 남기는 것을 `test_control_characters_in_the_path_cannot_forge_a_log_line`
 * 이 직접 본다(설계 문서 §3.2). 테스트가 없다는 이유로 이 줄을 지우지
 * 마라 — 노드 HTTP 파서가 막고 있는 경로가 바뀌면(예: 다른 프레임워크로
 * 교체) 그 즉시 필요해진다.
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
      // res.writeHead(status, ...) 를 직접 부르는 경로(예: SSE 라우트)에서는
      // 이 시점의 res.statusCode 가 아직 새 값으로 갱신되지 않았다 —
      // 노드의 ServerResponse.writeHead() 는 `this.statusCode = statusCode`
      // 를 자기 본문 **안에서** 실행하므로, 원래 writeHead 를 부르기 전에
      // res.statusCode 를 읽으면 그 전 값(기본 200)이 찍힌다. 지금까지는
      // 기본값이 우연히 200이라 눈에 안 띄었지만, res.writeHead(201, ...) 로
      // 실측하면 이 줄 없이는 "GET /probe 200"이 찍힌다 — 실제 응답은 201
      // 인데도. 첫 인자가 숫자면 그것을 쓰고, 아니면 res.statusCode 로
      // 떨어진다. 파이썬 access.py 가 ASGI send 의 message["status"] 를
      // 읽어 권위 있는 값을 얻는 것과 같은 결과를 만든다.
      const status = typeof args[0] === 'number' ? args[0] : res.statusCode;
      write(status);
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
