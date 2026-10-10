import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canGeneratePlan, dedupeStateReducer, initialDedupeState } from '../src/utils/dedupeState';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 advanced dedupe page authority dialogs', () => {
  test('only current, acknowledged preview digest allows generation, stale and errors fail closed', () => {
    const started = dedupeStateReducer(initialDedupeState, { type: 'PREVIEW_STARTED' });
    const ready = dedupeStateReducer(started, {
      type: 'PREVIEW_SUCCESS', digest: 'current-digest', requestGeneration: started.configGeneration,
    });
    assert.equal(canGeneratePlan(initialDedupeState), false);
    assert.equal(canGeneratePlan(started), false);
    assert.equal(canGeneratePlan(ready), true);
    assert.equal(ready.acceptedPreviewDigest, 'current-digest');
    assert.equal(canGeneratePlan(dedupeStateReducer(ready, { type: 'CONFIG_EDITED' })), false);
    assert.equal(canGeneratePlan(dedupeStateReducer(ready, { type: 'GENERATE_STARTED' })), false);
    assert.equal(canGeneratePlan(dedupeStateReducer(ready, {
      type: 'PREVIEW_CHANGED_ERROR', error: 'snapshot changed',
    })), false);
    assert.equal(canGeneratePlan(dedupeStateReducer(ready, {
      type: 'GENERATE_FAILED', error: 'plan rejected',
    })), false);
    assert.equal(canGeneratePlan(dedupeStateReducer(ready, { type: 'PREVIEW_STARTED' })), false);
    const stale = dedupeStateReducer(ready, { type: 'CONFIG_EDITED' });
    const rejected = dedupeStateReducer(stale, {
      type: 'PREVIEW_SUCCESS', digest: 'old-generation',
      requestGeneration: ready.configGeneration,
    });
    assert.equal(canGeneratePlan(rejected), false);
  });

  test('direct page uses Console controls and maintains all authority gates without Ant overlays', () => {
    const page = read('src/pages/Scans/AdvancedDedupePage.tsx');
    for (const part of [
      'useConsoleToast', 'DedupeActionDialog', '<ConsoleButton', '<ConsoleIcon',
      "scansApi.dedupePreview(scanId", "scansApi.createAdvancedDedupePlan(scanId",
      'expected_preview_digest: dedupeState.acceptedPreviewDigest',
      'scorer_config: previewedConfig', 'storage_action: previewedStorageAction',
      'previewData.planned_action_count === 0', '!canGeneratePlan(dedupeState)',
      'isDirty', 'generateInFlight.current', "setNotice('generate')",
      'dispatch({ type: \'GENERATE_STARTED\' })',
      "structured.code === 'PREVIEW_CHANGED'",
      "structured.code === 'DEDUPE_PREVIEW_CHANGED'",
      "dispatch({ type: 'PREVIEW_CHANGED_ERROR', error: formatted })",
      "setNotice('preview_changed')",
      "structured.code === 'DEDUPE_SCAN_NOT_FOUND'",
      "structured.code === 'DEDUPE_SCAN_NOT_COMPLETED'",
      "structured.code === 'DEDUPE_EMPTY_PLAN'",
      'handleRunPreview()', 'shouldAcceptDirectResponse',
      "dispatch({ type: 'CONFIG_EDITED' })",
      "type: 'PREVIEW_SUCCESS',",
      'setNotice(null); // Any pending confirmation refers to the old preview digest.',
      'setNotice(null); // Invalidate stale action confirmation.',
      "navigate('/plans/' + (res.id || res.plan_id))",
      'DedupePreviewTable', 'DedupeScorerConfigEditor', 'DedupeStorageActionPanel',
      'DedupeIdentitySafetyPanel', 'DedupePreviewSummaryPanel', 'DedupeExplainDrawer',
      'Freeze -> Validate -> Execute',
    ]) assert.ok(page.includes(part), part);
    assert.doesNotMatch(page, /from ['"]antd['"]|from ['"]@ant-design\/icons['"]|Modal\.(confirm|warning|info|error)|<Button\b|<Alert\b|<Spin\b|message\./);
    assert.doesNotMatch(page, /deleteFiles\(|executePlan\(/);
  });

  test('Radix authority dialog includes hardlink/reflink warnings, fail-closed busy and explicit recovery', () => {
    const dialog = read('src/components/dedupe/DedupeActionDialog.tsx');
    for (const part of [
      '<Dialog.Root', '<Dialog.Portal>', '<Dialog.Overlay', '<Dialog.Content',
      '<Dialog.Title>', '<Dialog.Description', 'onEscapeKeyDown',
      'onPointerDownOutside', 'if (busy) event.preventDefault()',
      "kind !== 'generate' && errorMessage", 'role="alert"',
      'Hardlink 后两个路径共享同一个 inode', 'Reflink 使用独立 inode',
      'PREVIEW_CHANGED', 'DEDUPE_SCAN_NOT_FOUND', 'DEDUPE_SCAN_NOT_COMPLETED',
      'DEDUPE_EMPTY_PLAN', '重新运行预览', '返回扫描详情',
      '生成后仅创建 Draft 状态计划', 'Freeze -&gt; Validate -&gt; Execute',
      '<ConsoleButton',
    ]) assert.ok(dialog.includes(part), part);
    assert.doesNotMatch(dialog, /from ['"]antd['"]|@ant-design\/icons/);
  });

  test('portal CSS follows light/dark/mobile/keyboard and reduced motion requirements', () => {
    const css = read('src/styles/console-v2-advanced-dedupe.css');
    for (const part of [
      '.nfc-v2-advanced-dedupe-dialog', '.nfc-v2-advanced-dedupe-overlay',
      '.nfc-v2-advanced-dedupe-dialog-actions', '.nfc-v2-dedupe-page-state',
      "[data-theme='dark']", ':focus-visible',
      '@media (max-width: 767px)', 'prefers-reduced-motion: reduce',
      'overscroll-behavior',
    ]) assert.ok(css.includes(part), part);
  });
});
