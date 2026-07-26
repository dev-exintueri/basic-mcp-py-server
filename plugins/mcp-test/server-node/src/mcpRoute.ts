/**
 * 세션별 transport 라우팅.
 *
 * 파이썬은 mcp.streamable_http_app() 이 이 일을 내부에서 처리하지만, 노드
 * SDK 는 transport 인스턴스를 우리가 들고 있어야 한다.
 *
 * 이 Map 은 registry 와 **다른 것**이다. registry 는 X-Client-Instance 로
 * 세는 우리 개념이고, 이 Map 은 MCP 프로토콜의 Mcp-Session-Id 로 도는 SDK
 * 사정이다. 둘을 섞지 않는다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** 없는 세션에 대한 응답 코드와 본문.
 *
 * **깨면 안 되는 것.** sessionIdGenerator 를 undefined 로 두지 않는다.
 * 그것이 stateless 모드이고, 세션 ID 가 발급되지 않아 sessionView 의
 * mcp_session_id 가 영원히 null 이 된다.
 */

import { randomUUID } from 'node:crypto';
import type { Request, RequestHandler, Response } from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { isInitializeRequest } from '@modelcontextprotocol/sdk/types.js';

export function mcpRoute(makeServer: () => McpServer): RequestHandler {
  const transports = new Map<string, StreamableHTTPServerTransport>();

  return async (req: Request, res: Response): Promise<void> => {
    const raw = req.headers['mcp-session-id'];
    const sessionId = Array.isArray(raw) ? raw[0] : raw;

    if (sessionId !== undefined && transports.has(sessionId)) {
      await transports.get(sessionId)!.handleRequest(req, res, req.body);
      return;
    }

    if (sessionId === undefined && isInitializeRequest(req.body)) {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (id: string) => {
          transports.set(id, transport);
        },
      });
      transport.onclose = () => {
        if (transport.sessionId !== undefined) transports.delete(transport.sessionId);
      };
      await makeServer().connect(transport);
      await transport.handleRequest(req, res, req.body);
      return;
    }

    if (sessionId !== undefined) {
      res.status(404).json({ error: '알 수 없는 세션이다. 새 세션을 시작하라' });
      return;
    }
    res.status(400).json({ error: 'Mcp-Session-Id 헤더가 필요하다' });
  };
}
