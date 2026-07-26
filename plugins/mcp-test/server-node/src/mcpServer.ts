/**
 * McpServer 인스턴스와 노출 도구 4개.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** 도구를 더하고 빼는 곳은 buildMcp() 안이다.
 *
 * **깨면 안 되는 것.** 인자 없는 도구의 콜백은 (extra) 하나만 받는다.
 * SDK 의 executeToolHandler 가 inputSchema 유무로 갈리기 때문이다 —
 * 있으면 (args, extra), 없으면 (extra). 습관대로 (_args, extra) 라고 쓰면
 * extra 가 첫 인자에 들어가고 두 번째는 undefined 가 되어, whoami 가
 * 연결 ID 를 조용히 놓친다. 오류는 나지 않는다.
 *
 * 헤더는 extra.requestInfo.headers 에서 **소문자 키**로 읽는다.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

import { UNKNOWN_INSTANCE } from './auth.js';
import { getLogger, type Clock } from './logging.js';
import { Registry, sessionView } from './registry.js';

const logger = getLogger('call');

type Extra = { requestInfo?: { headers?: Record<string, string | string[] | undefined> } };

function instanceIdOf(extra: Extra | undefined): string {
  const raw = extra?.requestInfo?.headers?.['x-client-instance'];
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value || UNKNOWN_INSTANCE;
}

function textResult(payload: unknown) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(payload) }] };
}

/** 도구 호출을 한 줄 남긴다. 파이썬 쪽 _logged 데코레이터와 같은 역할이다. */
function logged<T>(name: string, extra: Extra | undefined, run: () => T): T {
  const started = process.hrtime.bigint();
  const instance = instanceIdOf(extra);
  try {
    const result = run();
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    logger.info(`tool=${name} instance=${instance} dur_ms=${ms.toFixed(0)} ok`);
    return result;
  } catch (error) {
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    logger.warn(
      `tool=${name} instance=${instance} dur_ms=${ms.toFixed(0)} ` +
        `error=${(error as Error).constructor.name}`,
    );
    throw error;
  }
}

export function buildMcp(registry: Registry, startedAt: Date, clock: Clock): McpServer {
  const mcp = new McpServer({ name: 'mcp-test-server', version: '0.1.0' });

  mcp.registerTool(
    'ping',
    {
      description:
        '서버 프로세스 정보를 반환한다. 여러 세션이 같은 pid를 보면 한 프로세스를 공유하는 것이다.',
    },
    (extra) =>
      logged('ping', extra as Extra, () => {
        const now = clock();
        return textResult({
          pid: process.pid,
          uptime_seconds: (now.getTime() - startedAt.getTime()) / 1000,
          session_count: registry.all().length,
          server_time: now.toISOString(),
        });
      }),
  );

  mcp.registerTool(
    'echo',
    { description: '받은 문자열을 그대로 돌려준다.', inputSchema: { text: z.string() } },
    (args, extra) =>
      logged('echo', extra as Extra, () => ({
        content: [{ type: 'text' as const, text: args.text }],
      })),
  );

  mcp.registerTool(
    'whoami',
    { description: '이 세션이 서버에 어떻게 보이는지 반환한다.' },
    (extra) =>
      logged('whoami', extra as Extra, () => {
        const instanceId = instanceIdOf(extra as Extra);
        const record = registry.get(instanceId);
        if (record === undefined) return textResult({ instance_id: instanceId, known: false });
        return textResult({ known: true, ...sessionView(record, registry, clock()) });
      }),
  );

  mcp.registerTool(
    'sessions',
    { description: '이 서버에 붙어 있는 모든 세션을 반환한다.' },
    (extra) =>
      logged('sessions', extra as Extra, () => {
        const now = clock();
        return textResult({
          count: registry.all().length,
          sessions: registry.all().map((r) => sessionView(r, registry, now)),
        });
      }),
  );

  return mcp;
}
