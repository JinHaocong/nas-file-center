import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Hardlink / Reflink Advanced Dedupe UI', () => {
  test('storage action is explicit and quarantine remains the default', () => {
    const page = read('src/pages/Scans/AdvancedDedupePage.tsx');
    const types = read('src/types/dedupe.ts');

    assert.match(types, /DedupeStorageAction = 'quarantine' \| 'hardlink' \| 'reflink'/);
    assert.match(page, /useState<DedupeStorageAction>\('quarantine'\)/);
    assert.match(page, /隔离（默认，保留可撤销路径）/);
    assert.match(page, /Hardlink 空间优化/);
    assert.match(page, /Reflink \/ CoW 空间优化/);
  });

  test('preview and generate bind the selected storage action', () => {
    const page = read('src/pages/Scans/AdvancedDedupePage.tsx');
    const types = read('src/types/dedupe.ts');

    assert.match(page, /storage_action: variables\.storageAction/);
    assert.match(page, /setPreviewedStorageAction\(variables\.storageAction\)/);
    assert.match(page, /storage_action: previewedStorageAction \|\| 'quarantine'/);
    assert.match(page, /handleStorageActionChange[\s\S]*CONFIG_EDITED/);
    assert.match(types, /storage_action\?: DedupeStorageAction/);
  });

  test('Hardlink generate confirmation states shared inode semantics explicitly', () => {
    const page = read('src/pages/Scans/AdvancedDedupePage.tsx');

    assert.match(page, /Hardlink 会让两个路径共享同一个 inode/);
    assert.match(page, /未来通过任一路径写入都会修改同一份文件内容/);
    assert.match(page, /我理解共享 inode，生成草案/);
  });

  test('Reflink explains independent inode and live capability verification', () => {
    const page = read('src/pages/Scans/AdvancedDedupePage.tsx');
    const summary = read('src/components/dedupe/DedupePreviewSummaryPanel.tsx');

    assert.match(page, /Reflink 使用写时复制语义/);
    assert.match(page, /目标路径保持独立 inode/);
    assert.match(summary, /Reflink 优化保留独立 inode/);
    assert.match(summary, /Validate \/ Execute/);
  });

  test('preview table exposes optimization decisions and blocking reasons', () => {
    const table = read('src/components/dedupe/DedupePreviewTable.tsx');
    const drawer = read('src/components/dedupe/DedupeExplainDrawer.tsx');
    const preview = read('src/utils/dedupePreview.ts');

    assert.match(preview, /norm === 'HARDLINK'/);
    assert.match(preview, /norm === 'REFLINK'/);
    assert.match(table, /storage_blocking_reason/);
    assert.match(table, /storage_capability/);
    assert.match(table, /Hardlink/);
    assert.match(table, /Reflink/);
    assert.match(drawer, /存储优化判定/);
    assert.match(drawer, /storage_blocking_reason/);
    assert.match(drawer, /storage_capability/);
  });

  test('generate availability uses generic planned action count', () => {
    const page = read('src/pages/Scans/AdvancedDedupePage.tsx');
    const summary = read('src/components/dedupe/DedupePreviewSummaryPanel.tsx');

    assert.match(page, /previewData\.planned_action_count \?\?/);
    assert.match(summary, /summary\.planned_action_count \?\?/);
    assert.match(summary, /storage_blocked_count/);
  });
});
