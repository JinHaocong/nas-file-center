import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C4B safety and data surfaces contract', () => {
  test('Quarantine uses responsive safety cards and preserves all mutation gates', () => {
    const source = read('src/pages/Quarantine/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'CodePath', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-quarantine-mobile-card/);
    for (const semantic of [
      'ALLOW_MUTATION=false',
      'ALLOW_DELETE=false',
      'isAdmin',
      'getBulkSelectableEntryIds',
      'resolveBulkFilteredEntryIds',
      'BulkRestoreModal',
      'BulkPurgeModal',
      'PurgeConfirmModal',
      'RestoreModal',
    ]) {
      assert.match(source, new RegExp(semantic));
    }
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Audit uses responsive event cards and retains search retention and detail semantics', () => {
    const source = read('src/pages/Audit/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'CodePath', 'StatusBadge']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-audit-mobile-card/);
    assert.match(source, /formatAuditRetention/);
    assert.match(source, /auditApi\.listEvents/);
    assert.match(source, /selectedEvent/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('Indexes uses responsive root cards and preserves reindex/remove safety rules', () => {
    const source = read('src/pages/Indexes/index.tsx');
    for (const symbol of ['PageHeader', 'DataPanel', 'ActionBar', 'ResponsiveDataView', 'CodePath']) {
      assert.match(source, new RegExp(symbol));
    }
    assert.match(source, /nfc-index-mobile-card/);
    assert.match(source, /record\.can_remove/);
    assert.match(source, /record\.path_state === ['"]available['"]/);
    assert.match(source, /DirectoryPicker/);
    assert.match(source, /不会删除 NAS 上的任何真实文件或目录/);
    assert.doesNotMatch(source, /<Card\b/);
  });

  test('C4B CSS defines dedicated safety/data mobile surfaces', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-quarantine-mobile-card',
      '.nfc-audit-mobile-card',
      '.nfc-index-mobile-card',
      '.nfc-bulk-action-bar',
      '.nfc-audit-detail',
      '.nfc-selection-count',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
  });
});
