import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { api } from '../src/api/client';
import { quarantineApi } from '../src/api/quarantine';

const read = (file: string) => readFileSync(resolve(process.cwd(), file), 'utf8');

describe('externally missing quarantine payload metadata-only cleanup', () => {
  test('uses a separate, exact-confirmation endpoint instead of permanent purge', async () => {
    const original = api.delete;
    let path = '';
    api.delete = ((endpoint: string) => {
      path = endpoint;
      return Promise.resolve({ status: 'ok', deleted: true, id: 1106, metadata_only: true });
    }) as typeof api.delete;
    try {
      const result = await quarantineApi.cleanupMissingRecord(1106);
      assert.equal(path, '/api/quarantine/1106/missing-record?confirmation=CLEANUP_MISSING_RECORD');
      assert.equal(result.metadata_only, true);
    } finally {
      api.delete = original;
    }
  });

  test('requires an admin and explicit confirmation, and never widens terminal deletion', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /record\.state === 'active' \|\| record\.state === 'purging'/);
    assert.match(source, /\) && isAdmin && \(/);
    assert.match(source, /清理缺失文件记录/);
    assert.match(source, /cleanupMissingRecordMutation\.mutateAsync\(target\.id\)/);
    assert.match(source, /onConfirm=\{\(\) => \{ void handleConfirmMissingCleanup\(\); \}\}/);
    assert.match(source, /确认仅删除数据库记录/);
    assert.match(source, /不会删除任何文件/);
    assert.match(source, /isSafeMode \|\| !allowDelete/);
    assert.match(source, /\['restored', 'purged', 'abandoned', 'conflict'\]\.includes\(record\.state\)/);
  });

  test('does not silently convert recovery diagnosis into destructive mutation', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    assert.match(source, /quarantineApi\.recoveryDiagnostic\(entryId\)/);
    assert.match(source, /没有执行删除、状态重置或事务恢复/);
    assert.match(source, /安全校验未通过，记录已保留/);
    const client = read('src/api/quarantine.ts');
    assert.match(client, /\/missing-record\?confirmation=CLEANUP_MISSING_RECORD/);
    assert.match(client, /\/record\?confirmation=DELETE_RECORD/);
  });
});
