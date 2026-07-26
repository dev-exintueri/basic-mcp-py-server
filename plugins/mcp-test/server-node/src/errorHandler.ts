/**
 * 라우트가 던진 예외를 받는 마지막 방어선 — express 오류 미들웨어.
 *
 * 이게 없으면 body-parser 의 SyntaxError/PayloadTooLargeError 같은 것들이
 * express 기본 처리기(finalhandler)로 떨어진다. finalhandler 는 개발
 * 모드가 아니면 스택은 안 보내지만, 응답 본문에 `err.message` 를 HTML
 * `<pre>` 로 그대로 박아 넣고 — 이 서버 계약(§3.1)이 요구하는 JSON
 * `{error}` 형태가 아니다 — 그리고 그 예외를 **로그 파일에도, SSE
 * 스트림에도, 관리 화면 백필에도 남기지 않는다.** 이 서버의 존재 이유가
 * 그 화면이므로(app.ts 의 close() 주석 참고) 관측 불가는 기능 결손이다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** 로그 문구.
 *
 * **함께 바꿔야 하는 것.** `main.ts` 의 `process.on('unhandledRejection'
 * /'uncaughtException')` 도 같은 로거(`getLogger('app')`)를 쓴다 — 파이썬
 * `app.py` 의 `_loop_exception_handler` 와 자리가 맞는다. 두 곳 다 "예외를
 * 삼키지 않고 관측 가능한 곳에 남긴다"는 같은 목적이다.
 *
 * **깨면 안 되는 것.**
 * - 인자 개수. express(5 포함) 는 함수의 인자 **개수**로 오류 미들웨어를
 *   가려낸다 — 4개면 오류 미들웨어, 아니면 보통 미들웨어다. `next` 를
 *   쓰지 않는다고 지우면(3개로 줄이면) 이 함수는 오류를 다시는 못 받는다.
 *   미사용 인자에는 이름에 밑줄만 붙인다.
 * - 응답에 `err.stack` 을 담지 않는다. 서버 소스의 절대 경로와 의존성
 *   파일·행 번호가 새어 나간다 — 토큰 없이도 닿는 경로라 더 심각하다
 *   (`err.message` 는 body-parser 의 SyntaxError/PayloadTooLargeError 로
 *   실측한 결과 경로를 담지 않았다. 다른 예외가 메시지에 경로를 넣지
 *   않는지는 각자 고쳐 넣는 사람의 몫이다).
 */

import type { ErrorRequestHandler } from 'express';

import { getLogger } from './logging.js';

const logger = getLogger('app');

function statusOf(err: unknown): number {
  if (typeof err === 'object' && err !== null && 'status' in err) {
    const status = (err as { status?: unknown }).status;
    if (typeof status === 'number') return status;
  }
  return 500;
}

export const errorHandler: ErrorRequestHandler = (err, _req, res, next) => {
  const message = err instanceof Error ? err.message : String(err);
  logger.error(`요청 처리 중 예외: ${message}`);

  if (res.headersSent) {
    // 응답이 이미 시작된 뒤라면(예: 스트리밍 도중 오류) 여기서 다시
    // res.json() 을 부르면 "헤더를 두 번 보냈다"는 새 오류가 난다. express
    // 문서가 권하는 대로 기본 오류 처리기에 넘긴다.
    next(err);
    return;
  }
  res.status(statusOf(err)).json({ error: message });
};
