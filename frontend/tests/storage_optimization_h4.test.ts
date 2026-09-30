import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { classifyMemberDecision } from '../src/utils/dedupePreview.js';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Storage Optimization H4 frontend contract', () => {
  const pageSource = read('src/pages/Scans/AdvancedDedupePage.tsx');
  const panelSource = read('src/components/dedupe/DedupeStorageActionPanel.tsx');
  const typesSource = read('src/types/dedupe.ts');
  const apiSource = read('src/api/domain.ts');
  const summarySource = read('src/components/dedupe/DedupePreviewSummaryPanel.tsx');
  const tableSource = read('src/components/dedupe/DedupePreviewTable.tsx');
  const explainSource = read('src/components/dedupe/DedupeExplainDrawer.tsx');
  const planSource = read('src/pages/Plans/PlanDetail.tsx');

  test('quarantine stays the explicit frontend default', () => {
    assert.match(pageSource, /useState<DedupeStorageAction>\('quarantine'\)/);
    assert.match(panelSource, /默认保持 Quarantine/);
  });

  test('preview and Generate bind the selected storage_action to the accepted digest flow', () => {
    assert.match(pageSource, /storage_action:\s*variables\.storageAction/);
    assert.match(pageSource, /setPreviewedStorageAction\(variables\.storageAction\)/);
    assert.match(pageSource, /previewedStorageAction !== storageAction/);
    assert.match(pageSource, /storage_action:\s*previewedStorageAction/);
    assert.match(pageSource, /planned_action_count === 0/);
    assert.match(typesSource, /storage_action\?:\s*DedupeStorageAction/);
  });

  test('hardlink and reflink decisions are not misclassified as skipped', () => {
    const hardlink = classifyMemberDecision('HARDLINK');
    const reflink = classifyMemberDecision('REFLINK');
    assert.strictEqual(hardlink.kind, 'HARDLINK');
    assert.strictEqual(hardlink.label, 'HARDLINK');
    assert.strictEqual(reflink.kind, 'REFLINK');
    assert.strictEqual(reflink.label, 'REFLINK');
    assert.match(tableSource, /Hardlink 优化/);
    assert.match(tableSource, /Reflink 优化/);
  });

  test('hardlink warning explicitly states shared-inode future write semantics', () => {
    const warning = 'Hardlink 后两个路径共享同一个 inode，未来通过任一路径写入都会修改同一份文件内容。';
    assert.match(panelSource, new RegExp(warning));
    assert.match(planSource, new RegExp(warning));
  });

  test('reflink is described as independent inode Copy-on-Write, not a full copy', () => {
    assert.match(panelSource, /独立 inode/);
    assert.match(panelSource, /Copy-on-Write/);
    assert.match(panelSource, /不是普通完整复制/);
    assert.match(planSource, /独立 inode/);
    assert.match(planSource, /Copy-on-Write/);
  });

  test('capability diagnostics are explicit admin-only probes of the actual KEEP-to-SOURCE parent route', () => {
    assert.match(apiSource, /\/api\/storage-optimization\/capabilities/);
    assert.match(pageSource, /source_directory:\s*diagnosticPair\.keepParent/);
    assert.match(pageSource, /destination_directory:\s*diagnosticPair\.sourceParent/);
    assert.match(pageSource, /onProbeCapabilities=\{\(\) => capabilityMutation\.mutate\(\)\}/);
    assert.match(panelSource, /显式探测当前路径对/);
    assert.match(panelSource, /不会在 Preview \/ Generate 中自动运行/);
    assert.match(panelSource, /Validate \/ Worker Execute 仍会对实际路径重新验证能力/);
    assert.match(panelSource, /Hardlink \/ Reflink 仅管理员可生成、冻结、验证和执行/);
  });

  test('metadata eligibility and blocking diagnostics are surfaced without capability guessing', () => {
    assert.match(typesSource, /storage_metadata_compatible\?:\s*boolean \| null/);
    assert.match(typesSource, /storage_blocking_reason\?:\s*string \| null/);
    assert.match(explainSource, /Preview 只做 metadata eligibility，不执行 filesystem capability probe/);
    assert.match(tableSource, /record\.storage_blocking_reason/);
    assert.match(summarySource, /storage_blocked_count/);
  });
});
