import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('quarantine terminal record cleanup', () => {
  test('frontend quarantine state model includes conflict', () => {
    const source = read('src/types/quarantine.ts');
    assert.match(source, /\| 'conflict'/);
  });

  test('filtered record cleanup resolves purged abandoned and conflict', () => {
    const source = read('src/api/quarantine.ts');
    assert.match(source, /resolveTerminalCleanupFilteredEntryIds/);
    assert.match(source, /'purged', 'abandoned', 'conflict'/);
  });

  test('single-record cleanup is exposed for all supported terminal states', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /\['purged', 'abandoned', 'conflict'\]\.includes\(record\.state\)/);
    assert.match(source, /冲突 \(conflict\)/);
    assert.match(source, /批量删除终态记录/);
  });
});
