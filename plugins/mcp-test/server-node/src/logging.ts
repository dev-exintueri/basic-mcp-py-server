/**
 * 로그 줄의 형식과 목적지.
 *
 * 파이썬 쪽은 표준 logging 의 루트 로거에 핸들러를 붙이지만, 노드에는
 * 그런 전역 로깅이 없다. 대신 카테고리별 로거를 만들어 같은 형식의 줄을
 * 같은 목적지로 보낸다. 목적지는 프로세스 전역 상태이므로 configureLogging()
 * 이 한 번만 정한다.
 *
 * 스탬프에 밀리초를 남기지 않는다. toISOString() 은 붙이므로 잘라낸다 —
 * 파이썬의 strftime("%Y-%m-%dT%H:%M:%SZ") 와 같은 줄을 만들기 위해서다.
 *
 * ## 응용할 때
 *
 * **바꿔도 되는 것.** formatLine() 의 줄 형식과 레벨 이름.
 *
 * **함께 바꿔야 하는 것.** 줄 형식을 바꾸면 관리 화면의 로그 패널과
 * logPaths 의 tailLines() 백필이 그 형식을 그대로 보여주므로 함께 본다.
 * 그리고 conformance 스위트가 이 형식을 단언한다.
 *
 * **깨면 안 되는 것.**
 * - 카테고리가 8칸을 넘어도 자르지 않는다. 자르면 어느 로거가 냈는지 알 수 없어진다.
 * - 시계는 configureLogging() 으로 반드시 주입된다. 모듈 안에서 new Date() 를
 *   부르지 않는다. configureLogging() 이전의 로그 호출은 아무 데도 나가지 않는다.
 * - sink 예외는 삼키되, stderr 로 오류를 알린다. 한 목적지의 실패가 나머지
 *   목적지에 영향을 주면 안 된다.
 * - dailyFileSink() 의 쓰기 실패도 같은 이유로 삼킨다. 이 sink 는 접근 로그
 *   미들웨어와 모든 도구 호출 안에서 돌므로, 디스크가 꽉 찼다고 요청 처리가
 *   죽으면 안 된다.
 * - formatLine() 이 캐리지 리턴과 줄바꿈을 이스케이프하는 **유일한** 자리다.
 *   호출자마다 거는 방식(access.ts 가 원래 그렇게 했다)은 새 호출자가
 *   생길 때마다 다시 걸어야 하고, 하나라도 빠뜨리면 그 호출자를 거치는
 *   메시지만 조용히 샌다 — 실제로 errorHandler.ts 가 body-parser 의
 *   SyntaxError 메시지(V8 이 요청 본문 앞부분을 그대로 되울린다)를 손보지
 *   않고 logger.error() 에 넘기면서 이 구멍에 걸렸다: 본문에 진짜 CR/LF 를
 *   심으면 로그 줄 하나가 둘로 쪼개졌다(최종 리뷰 재재검토, 실측). 이
 *   함수가 모든 sink 호출의 유일한 조립 지점이므로 여기서 한 번 걸면
 *   지금 있는 호출자와 앞으로 생길 모든 호출자를 함께 덮는다. access.ts
 *   의 기존 이스케이프는 이미 escape 된 문자열을 다시 escape 하는 것뿐이라
 *   무해하니 지우지 않는다.
 */

import { appendFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { logFileName } from './logPaths.js';

export type Clock = () => Date;
export type Level = 'INFO' | 'WARN' | 'ERROR';

export function stamp(clock: Clock): string {
  return clock().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function formatLine(
  clock: Clock,
  level: Level,
  category: string,
  message: string,
): string {
  const line = `${stamp(clock)} ${level.padEnd(5)} ${category.padEnd(8)} ${message}`;
  // 캐리지 리턴과 줄바꿈을 조립이 끝난 한 줄에 한 번 건다 — 이유는 위
  // 모듈 주석의 "깨면 안 되는 것"에 있다. message 는 호출자마다 다른
  // 곳(요청 경로, 예외 메시지, ...)에서 오므로 여기서 막아야 새 호출자가
  // 생겨도 조용히 새지 않는다.
  return line.replace(/\r/g, '\\r').replace(/\n/g, '\\n');
}

export interface Logger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

export type Sink = (line: string) => void;

let sinks: Sink[] = [];
let currentClock: Clock | null = null;

export function configureLogging(options: { clock: Clock; sinks: Sink[] }): void {
  currentClock = options.clock;
  sinks = options.sinks;
}

export function resetLogging(): void {
  sinks = [];
  currentClock = null;
}

export function getLogger(category: string): Logger {
  const emit = (level: Level, message: string): void => {
    // configureLogging() 이전, 또는 sinks 가 없으면 아무 데도 나가지 않는다.
    if (!currentClock || sinks.length === 0) {
      return;
    }
    const line = formatLine(currentClock, level, category, message);
    for (const sink of sinks) {
      try {
        sink(line);
      } catch (error) {
        // 로깅이 애플리케이션을 죽이면 안 된다. 한 목적지가 실패해도
        // 나머지 목적지에는 남긴다. 오류는 stderr 로 알린다.
        try {
          const message = error instanceof Error ? error.message : String(error);
          process.stderr.write(`[logging error] ${message}\n`);
        } catch {
          // stderr 쓰기도 실패하면 무시한다.
        }
      }
    }
  };
  return {
    info: (m) => emit('INFO', m),
    warn: (m) => emit('WARN', m),
    error: (m) => emit('ERROR', m),
  };
}

/**
 * 하루 한 파일. 날짜 경계는 주입된 시계로 판단한다.
 *
 * 쓰기 실패를 삼킨다. 로그 실패가 요청 처리를 통째로 죽이면 안 된다 —
 * 이 sink 는 접근 로그 미들웨어와 모든 도구 호출 안에서 돈다.
 */
export function dailyFileSink(
  logDir: string,
  port: number,
  clock: Clock,
): { sink: Sink; currentPath: () => string } {
  let day = clock().toISOString().slice(0, 10);
  let path = join(logDir, logFileName(port, clock()));

  return {
    sink: (line: string) => {
      const today = clock().toISOString().slice(0, 10);
      if (today !== day) {
        day = today;
        path = join(logDir, logFileName(port, clock()));
      }
      try {
        appendFileSync(path, line + '\n', 'utf8');
      } catch {
        // 삼킨다. 이유는 위 주석에 있다.
      }
    },
    currentPath: () => path,
  };
}

export function ensureLogDir(logDir: string): boolean {
  try {
    mkdirSync(logDir, { recursive: true });
    return true;
  } catch (error) {
    process.stderr.write(
      `경고: 로그 디렉토리 ${logDir} 를 쓸 수 없다 (${String(error)}). 파일 로깅 없이 계속한다.\n`,
    );
    return false;
  }
}
