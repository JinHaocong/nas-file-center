import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');
const browser = read('scripts/browser-task-overlays.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');
const css = read('src/styles/console-v2-task-overlays.css');

describe('Pure White Stage 5B: real Tasks portal visual acceptance contract', () => {
  test('Chromium opens native Task Sheet then actual Radix nested confirmation and history', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      "page.goto(BASE_URL + '/tasks'",
      "getByRole('button', { name: '详情' })",
      "getByRole('button', { name: '删除任务 #42' })",
      "page.locator('.nfc-v2-confirm-dialog')",
      "page.keyboard.press('Escape')",
      "getByRole('button', { name: '清理历史' })",
      "page.locator('.nfc-v2-history-dialog')",
      "page.screenshot(",
    ]) assert.ok(browser.includes(token), token);
  });

  test('32 read-only browser cases check overlay computations and block all writes', () => {
    assert.ok(browser.includes('360, 390, 430, 768, 1024, 1280, 1440, 1920'));
    assert.ok(browser.includes("mode: 'system', system: 'dark'"));
    assert.ok(browser.includes("mode: 'system', system: 'light'"));
    for (const token of [
      "request.method() !== 'GET'",
      'status: 405',
      "body: JSON.stringify({ detail: 'READ_ONLY_VISUAL_FIXTURE' })",
      'assert.deepEqual(writes, []',
      'getComputedStyle(node)',
      "x.filter === 'none'",
      'elementFromPoint',
      "assert.equal(completed, 32)",
      'reducedMotion',
    ]) assert.ok(browser.includes(token), token);
    assert.doesNotMatch(browser, /fetch\(\s*['"]https?:\/\/[^'"]*nas/i);
  });

  test('Task Sheet and confirmations retain exact intended stacking and semantic danger', () => {
    for (const token of [
      '.nfc-v2-sheet-overlay { z-index: 1100',
      'z-index: 1101',
      '.nfc-v2-confirm-overlay { z-index: 1300',
      'z-index: 1301',
      '.nfc-v2-confirm-dialog .nfc-v2-dialog-icon.is-danger',
      '.nfc-v2-history-warning',
      '.nfc-v2-history-statuses',
      "[data-theme='dark'] .nfc-v2-confirm-dialog",
      "background: var(--v2-paper)",
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/styles/console-v2.css').includes('backdrop-filter: none;'));
  });

  test('business rules keep terminal-only cleanup and explicit separate confirmation', () => {
    const detail = read('src/components/tasks/TaskDetailDrawer.tsx');
    const del = read('src/components/tasks/TaskDeleteButton.tsx');
    const cleanup = read('src/components/tasks/TaskHistoryCleanupModal.tsx');
    const confirm = read('src/components/ui/ConsoleConfirmDialog.tsx');
    assert.ok(detail.includes('<ConsoleSheet'));
    assert.ok(del.includes('getTaskDeleteAvailability(task)'));
    assert.ok(del.includes('<ConsoleConfirmDialog'));
    assert.ok(del.includes('onConfirm={confirmDelete}'));
    assert.ok(cleanup.includes("['completed', 'failed', 'cancelled']"));
    assert.ok(cleanup.includes('disabled={selectedStatuses.length === 0 || cleanupMutation.isPending}'));
    assert.ok(confirm.includes('onPointerDownOutside={event => event.preventDefault()}'));
    assert.ok(confirm.includes('if (busy) event.preventDefault()'));
    assert.doesNotMatch(browser, /tasksApi\.(deleteTask|clearTaskHistory)\(/);
  });

  test('CI executes both browser matrices on exact candidate and uploads both evidence folders', () => {
    for (const marker of [
      'Checkout exact candidate HEAD',
      'Verify candidate identity',
      'playwright@1.56.1',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'frontend/artifacts/browser-overlay/*.png',
      'frontend/artifacts/browser-task-overlay/*.png',
    ]) assert.ok(workflow.includes(marker), marker);
    assert.ok(workflow.includes('Run read-only Chromium Tasks modal and nested Sheet matrix'));
  });
});
