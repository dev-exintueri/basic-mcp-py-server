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
 *
 * **함께 바꿔야 하는 것.** logged() 의 두 번째 인자로 extra 를 넘길지는
 * 파이썬 mcp_server.py 의 함수 시그니처가 정한다 — ctx: Context 를 받는
 * 도구(whoami)만 실제 연결 ID 를 로그에 남기고, 나머지(ping, echo,
 * sessions)는 ctx 가 없어 항상 instance=unknown 이다(Task 11, conformance 의
 * test_tool_call_without_ctx_logs_unknown_instance 가 실측). 새 도구를
 * 더하거나 기존 도구에 ctx 상당의 인자를 붙일 때 이 표를 먼저 본다 —
 * extra 가 손에 있다고 무조건 넘기면 파이썬과 갈린다.
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

/**
 * 도구 호출을 한 줄 남긴다. 파이썬 쪽 _logged 데코레이터와 같은 역할이다.
 *
 * export 하는 이유는 딱 하나, tests/mcpServer.test.ts 가 실패 분기(catch 블록)를
 * 직접 두들겨 보기 위해서다 — 파이썬 쪽도 같은 이유로 _logged 를 테스트가 직접
 * import 한다(test_mcp_server.py 의 test_tool_failure_is_logged_as_warning).
 * 도구 정의 밖에서 이 함수를 부를 다른 이유는 없다.
 */
export function logged<T>(name: string, extra: Extra | undefined, run: () => T): T {
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
    // extra 를 logged() 에 넘기지 않는다. 파이썬 ping() 은 ctx: Context 를
    // 받지 않으므로 _logged 의 kwargs.get("ctx") 가 항상 None 이라 로그의
    // instance 는 항상 unknown 이다 — extra 가 실제로 손에 있어도 안 쓰는
    // 것이 노드와 파이썬을 같게 만든다(conformance 의
    // test_tool_call_without_ctx_logs_unknown_instance 가 실측).
    () =>
      logged('ping', undefined, () => {
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
    // echo(text) 도 파이썬 쪽에 ctx 인자가 없다. 같은 이유로 extra 를
    // 넘기지 않는다 — 위 ping 의 주석 참고.
    (args) =>
      logged('echo', undefined, () => ({
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
    // sessions() 도 파이썬 쪽에 ctx 인자가 없다. 위 ping 의 주석 참고.
    () =>
      logged('sessions', undefined, () => {
        const now = clock();
        return textResult({
          count: registry.all().length,
          sessions: registry.all().map((r) => sessionView(r, registry, now)),
        });
      }),
  );

  return mcp;
}
