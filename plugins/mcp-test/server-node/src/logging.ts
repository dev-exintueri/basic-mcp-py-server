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
 */

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
  return `${stamp(clock)} ${level.padEnd(5)} ${category.padEnd(8)} ${message}`;
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
