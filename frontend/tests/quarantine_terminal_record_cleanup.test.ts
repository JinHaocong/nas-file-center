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

  test('filtered record cleanup resolves restored and terminal cleanup states', () => {
    const source = read('src/api/quarantine.ts');
    assert.match(source, /resolveTerminalCleanupFilteredEntryIds/);
    assert.match(source, /'restored', 'purged', 'abandoned', 'conflict'/);
  });

  test('single-record cleanup is exposed for all supported terminal states', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /\['restored', 'purged', 'abandoned', 'conflict'\]\.includes\(record\.state\)/);
    assert.match(source, /冲突 \(conflict\)/);
    assert.match(source, /批量删除记录/);
  });
  test('interrupted purge offers admin-only read-only diagnosis rather than deletion', () => {
    const page = read('src/pages/Quarantine/index.tsx');
    const api = read('src/api/quarantine.ts');
    const types = read('src/types/quarantine.ts');
    assert.match(page, /record\.state === 'purging' && isAdmin/);
    assert.match(page, /恢复诊断/);
    assert.match(page, /quarantineApi\.recoveryDiagnostic\(entryId\)/);
    assert.match(page, /automatic_cleanup_performed/);
    assert.match(page, /没有执行删除、状态重置或事务恢复/);
    assert.match(api, /\/api\/quarantine\/\$\{id\}\/recovery-diagnostic/);
    assert.match(types, /export interface QuarantineRecoveryDiagnostic/);
    assert.match(types, /transactional_purge_needs_authority/);
  });

});
