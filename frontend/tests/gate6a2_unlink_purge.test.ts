import test, { describe } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const readSource = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const pageSource = readSource('src/pages/Quarantine/index.tsx');
const bulkSource = readSource('src/pages/Quarantine/BulkPurgeModal.tsx');
const singleSource = readSource('src/pages/Quarantine/PurgeConfirmModal.tsx');
const typeSource = readSource('src/types/quarantine.ts');

const interfaceBlock = (name: string): string => {
  const match = typeSource.match(new RegExp(`export interface ${name} \\{[\\s\\S]*?\\n\\}`));
  assert.ok(match, `${name} interface must exist`);
  return match[0];
};

describe('Gate6-A2 unlink purge frontend contracts', () => {
  test('bulk permanent purge is gated by selection, admin, mutation and delete authority', () => {
    assert.doesNotMatch(pageSource, /批量永久删除在 v0\.3\.6 已暂缓/);
    assert.doesNotMatch(pageSource, /disabled=\{true\}/);

    const buttonIndex = pageSource.indexOf('批量永久删除');
    assert.notStrictEqual(buttonIndex, -1);
    const wiring = pageSource.slice(Math.max(0, buttonIndex - 1800), buttonIndex + 300);
    assert.match(wiring, /selectedEntryIds\.length/);
    assert.match(wiring, /isAdmin/);
    assert.match(wiring, /isSafeMode|allowMutation/);
    assert.match(wiring, /allowDelete/);
    assert.match(wiring, /setBulkPurgeOpen\(true\)/);
  });

  test('indexed hard-link survivor warning is visible but does not become mutation authority', () => {
    assert.match(bulkSource, /preview\.blocked_count === 0/);
    assert.match(bulkSource, /hardlink_survivor_paths/);
    assert.match(bulkSource, /survivor_status/);
    assert.match(bulkSource, /索引范围内|当前已建立索引的目录/);
    assert.match(bulkSource, /DELETE/);

    const canGenerateMatch = bulkSource.match(/const canGenerate = Boolean\([\s\S]*?\n  \);/);
    assert.ok(canGenerateMatch, 'BulkPurgeModal must keep an explicit Draft eligibility expression');
    const canGenerate = canGenerateMatch?.[0] ?? '';
    assert.ok(canGenerate, 'BulkPurgeModal Draft eligibility expression must be non-empty');
    assert.doesNotMatch(canGenerate, /survivor_status|hardlink_survivor|independent_copy/);
  });

  test('wording is pathname-unlink truthful and never claims secure physical erasure', () => {
    const combined = `${pageSource}\n${bulkSource}\n${singleSource}`;
    assert.doesNotMatch(
      combined,
      /彻底从磁盘|物理清除|永久彻底清除|彻底物理销毁|磁盘字节已完全擦除|物理删除/
    );
    assert.match(combined, /普通文件删除|unlink|文件系统删除/);
    assert.match(combined, /索引范围内|当前已建立索引的目录/);
  });

  test('same-content different-inode copies are displayed separately from hard-link survivors', () => {
    assert.match(bulkSource, /hardlink_survivor_paths/);
    assert.match(bulkSource, /independent_copy_paths/);
    assert.match(bulkSource, /hard link|hard-link|硬链接/i);
    assert.match(bulkSource, /同内容[^\n]*独立副本|独立副本/);
  });

  test('single Clear result uses the same scoped survivor/copy vocabulary as bulk', () => {
    assert.match(singleSource, /purge_semantics/);
    assert.match(singleSource, /survivor_scope/);
    assert.match(singleSource, /survivor_status/);
    assert.match(singleSource, /hardlink_survivor_paths/);
    assert.match(singleSource, /independent_copy_paths/);
    assert.match(singleSource, /索引范围内|当前已建立索引的目录/);
  });

  test('frontend types expose the Gate6-A2 backend advisory contract', () => {
    const previewItem = interfaceBlock('QuarantineBulkPreviewItem');
    for (const field of [
      'purge_semantics',
      'mutation_blockers',
      'survivor_scope',
      'survivor_status',
      'hardlink_survivor_count',
      'hardlink_survivor_paths',
      'same_content_scope',
      'same_content_status',
      'independent_copy_count',
      'independent_copy_paths',
      'advisory_diagnostics',
    ]) {
      assert.match(previewItem, new RegExp(`\\b${field}\\??:`), `missing ${field}`);
    }

    const purgeResponse = interfaceBlock('QuarantinePurgeResponse');
    for (const field of [
      'purge_semantics',
      'survivor_scope',
      'survivor_status',
      'hardlink_survivor_paths',
      'independent_copy_paths',
    ]) {
      assert.match(purgeResponse, new RegExp(`\\b${field}\\??:`), `missing ${field}`);
    }
  });
});
