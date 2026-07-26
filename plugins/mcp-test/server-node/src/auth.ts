/**
 * 요청 헤더에서 신원을 읽고, 인증하고, 차단한다.
 *
 * X-Client-Instance 는 클라이언트가 스스로 주장하는 값이고 검증하지 않는다.
 * sessions 도구가 모든 연결 ID 를 모든 세션에 공개하므로, 비어 있지 않은
 * 토큰만 있으면 누구나 남의 ID 로 요청을 보내 그 세션의 값을 덮어쓸 수 있다.
 * 피해는 제한적이고 이 설계에 내재한 성질이므로 막지 않는다. 사실로 남겨 둔다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** readIdentity() 의 통과 조건이 이 서버의 인증 전부다.
 * 진짜 인증을 넣는다면 여기다 — Identity 를 돌려주거나 null 을 돌려주기만
 * 하면 나머지는 그대로 동작한다.
 *
 * **함께 바꿔야 하는 것.** 헤더 이름을 바꾸면 플러그인 쪽 .mcp.json 의
 * headers 와 scripts/connection-id.sh 가 따라온다. Identity 에 필드를
 * 더하면 registry 의 touch() 도 따라온다.
 *
 * **깨면 안 되는 것.** 인증 미들웨어는 접근 로그 미들웨어보다 **나중에**
 * 등록해야 한다. express 에서 등록 순서가 곧 바깥/안쪽이고, 먼저 등록하면
 * 401/403 으로 거부된 요청이 접근 로그에 남지 않는다 — 이 서버에서 가장
 * 보고 싶은 줄이 그것이다.
 */

import { createHash } from 'node:crypto';
import type { IncomingHttpHeaders } from 'node:http';
import type { NextFunction, Request, RequestHandler, Response } from 'express';

import { getLogger } from './logging.js';
import type { Registry } from './registry.js';
import type { Clock } from './logging.js';

const registryLogger = getLogger('registry');

export const UNKNOWN_INSTANCE = 'unknown';
const BEARER_PREFIX = 'bearer ';

export interface Identity {
  subject: string;
  instanceId: string;
  project: string;
  label: string;
  mcpSessionId: string | null;
}

/** access.ts 가 읽는 요청 부착 정보. 스키마는 이 모듈이 정의한다. */
export interface AuthInfo {
  instance: string | null;
  subject: string | null;
  reason: string | null;
}

declare module 'express-serve-static-core' {
  interface Request {
    mcpTestAuth?: AuthInfo;
  }
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function readIdentity(headers: IncomingHttpHeaders): Identity | null {
  const authorization = first(headers['authorization']);
  if (authorization === undefined) return null;
  if (!authorization.toLowerCase().startsWith(BEARER_PREFIX)) return null;

  const subject = authorization.slice(BEARER_PREFIX.length).trim();
  if (!subject) return null;

  return {
    subject,
    instanceId: first(headers['x-client-instance']) || UNKNOWN_INSTANCE,
    project: first(headers['x-client-project']) || '',
    label: first(headers['x-client-label']) || 'unnamed',
    mcpSessionId: first(headers['mcp-session-id']) ?? null,
  };
}

export function maskSecret(value: string): string {
  if (!value) return '(empty)';
  const digest = createHash('sha256').update(value, 'utf8').digest('hex').slice(0, 8);
  return `${value.slice(0, 2)}…(sha256:${digest})`;
}

export function authMiddleware(registry: Registry, clock: Clock): RequestHandler {
  return (req: Request, res: Response, next: NextFunction): void => {
    const identity = readIdentity(req.headers);
    if (identity === null) {
      req.mcpTestAuth = { instance: null, subject: null, reason: 'blank-token' };
      res
        .status(401)
        .set('WWW-Authenticate', 'Bearer')
        .json({ error: 'Authorization 헤더에 비어 있지 않은 Bearer 토큰이 필요하다' });
      return;
    }

    if (registry.isBlocked(identity.instanceId)) {
      req.mcpTestAuth = {
        instance: identity.instanceId,
        subject: identity.subject,
        reason: 'blocked',
      };
      res
        .status(403)
        .json({ error: `연결 ${identity.instanceId} 이(가) 관리 화면에서 차단되었다` });
      return;
    }

    req.mcpTestAuth = {
      instance: identity.instanceId,
      subject: identity.subject,
      reason: null,
    };

    // DELETE 는 연결을 끊는 요청이지 새로 맺는 요청이 아니다. 아래 "처음 보는
    // 연결" 로그보다 먼저 갈라져야, 레지스트리가 모르는 인스턴스로 DELETE 가
    // 와도 connected 가 찍히지 않는다.
    if (req.method === 'DELETE') {
      registry.remove(identity.instanceId);
      next();
      return;
    }

    if (registry.get(identity.instanceId) === undefined) {
      // touch 하면 레코드가 생겨 버리므로 그 전에 본다.
      registryLogger.info(
        `connected instance=${identity.instanceId} ` +
          `subject=${maskSecret(identity.subject)} label=${identity.label}`,
      );
    }

    registry.touch({ ...identity, now: clock() });
    next();
  };
}
