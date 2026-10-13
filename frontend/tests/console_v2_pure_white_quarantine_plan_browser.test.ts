import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const single = read('src/styles/console-v2-quarantine-single-actions.css');
const bulk = read('src/styles/console-v2-quarantine-bulk-dialogs.css');
const plans = read('src/styles/console-v2-plan-cleanup-controls.css');
const browser = read('scripts/browser-quarantine-plan-overlays.mjs');

describe('Pure White Stage 5C Quarantine and Plan portal layering', () => {
  test('all feature-owned confirmations sit above shared z1300 scrim', () => {
    for (const [css, selector] of [
      [single, ".nfc-v2-quarantine-dialog.nfc-v2-dialog[data-state='open']"],
      [bulk, ".nfc-v2-quarantine-bulk-dialog.nfc-v2-dialog[data-state='open']"],
      [plans, ".nfc-v2-plan-history-dialog.nfc-v2-dialog[data-state='open']"],
    ] as const) {
      assert.ok(css.includes(selector + ' { z-index:1301; }'), selector);
    }
    const task = read('src/styles/console-v2-task-overlays.css');
    assert.ok(task.includes('.nfc-v2-confirm-overlay { z-index: 1300 !important; }'));
    assert.ok(task.includes(".nfc-v2-confirm-dialog.nfc-v2-dialog[data-state='open'] { z-index: 1301 !important"));
  });

  test('no blur or global CSS override introduced; keep semantic danger style', () => {
    const css = read('src/styles/console-v2.css');
    assert.match(css, /\.nfc-v2-dialog-overlay\s*\{[^}]*backdrop-filter:\s*none;/);
    assert.ok(single.includes('.nfc-v2-quarantine-alert.is-danger'));
    assert.ok(single.includes('.nfc-v2-quarantine-error'));
    assert.ok(bulk.includes('.nfc-v2-quarantine-bulk-note.is-danger'));
    assert.ok(plans.includes('.nfc-v2-plan-cleanup-warning'));
  });

  test('real Chromium fixture covers 32 width/theme cases with three dialog workflows', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      "page.goto(BASE_URL + '/quarantine'",
      "page.goto(BASE_URL + '/plans'",
      "getByRole('button', { name: '恢复', exact: true })",
      "getByRole('button', { name: '清除', exact: true })",
      "getByRole('button', { name: '清理计划历史' })",
      "getComputedStyle(dialog)",
      'document.elementFromPoint(x, y)',
      "assert.equal(completed, 32)",
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
    ]) assert.ok(browser.includes(token), token);
  });

  test('read-only fixture preserves exact DELETE and disallows all filesystem mutations', () => {
    for (const token of [
      "request.method() !== 'GET'",
      'status: 405',
      "await token.fill('delete')",
      "await token.fill('DELETE')",
      "assert.deepEqual(writes, []",
      'Only skip/rename/manual recovery strategies',
      'No plan statuses selected must disable destructive confirmation',
    ]) assert.ok(browser.includes(token), token);
    const purge = read('src/pages/Quarantine/PurgeConfirmModal.tsx');
    const restore = read('src/pages/Quarantine/RestoreModal.tsx');
    const plan = read('src/components/plans/PlanHistoryCleanupModal.tsx');
    assert.ok(purge.includes("quarantineApi.purge(entry.id, { confirmation: 'DELETE' })"));
    assert.ok(purge.includes('getQuarantinePurgeAvailability('));
    assert.ok(restore.includes('getQuarantineRestoreAvailability('));
    assert.ok(plan.includes('PLAN_HISTORY_OPTIONS.map(x => x.value)'));
    assert.doesNotMatch(browser, /quarantineApi\.(purge|restore)|plansApi\.clearHistory/);
  });

  test('browser CI uploads all three screenshot folders for exact candidate HEAD', () => {
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    for (const token of [
      'Checkout exact candidate HEAD',
      'Verify candidate identity',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'frontend/artifacts/browser-quarantine-plan/*.png',
      'frontend/artifacts/browser-task-overlay/*.png',
      'frontend/artifacts/browser-overlay/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
