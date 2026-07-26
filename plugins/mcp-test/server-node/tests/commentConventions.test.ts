import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = new URL('../src/', import.meta.url).pathname;
const SECTION = '## 응용할 때';

const modules = readdirSync(SRC).filter((name) => name.endsWith('.ts')).sort();

describe('주석 규약', () => {
  it('경로가 어긋나지 않았다', () => {
    // 경로가 틀리면 아래 테스트가 빈 목록을 돌며 조용히 통과한다.
    expect(modules.length).toBeGreaterThanOrEqual(9);
    expect(modules).toContain('app.ts');
  });

  it.each(modules)('%s 는 응용 방법을 적는다', (name) => {
    const text = readFileSync(join(SRC, name), 'utf8');
    const head = text.slice(0, text.indexOf('*/') + 2);
    expect(head.startsWith('/**')).toBe(true);
    expect(head).toContain(SECTION);
  });
});
