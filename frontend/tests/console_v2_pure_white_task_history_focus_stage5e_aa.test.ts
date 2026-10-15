import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const modal = read('src/components/tasks/TaskHistoryCleanupModal.tsx');
const browser = read('scripts/browser-task-overlays.mjs');

describe('Pure White Stage 5E-AA Task History controlled dialog focus return', () => {
  test('remembers the actual launcher before Radix autofocus without a fake Trigger', () => {
    for (const token of [
      'const returnFocusTarget = useRef<HTMLElement | null>(null);',
      'onOpenAutoFocus={() => {',
      'const active = document.activeElement;',
      'active instanceof HTMLElement && active !== document.body',
      'returnFocusTarget.current = active',
      '<Dialog.Root open={open}',
      'onClick={handleOpen}',
    ]) assert.ok(modal.includes(token), token);
    assert.doesNotMatch(modal, /<Dialog\\.Trigger/);
  });

  test('restores connected, enabled launcher only and preserves cleanup authority', () => {
    for (const token of [
      'onCloseAutoFocus={event => {',
      'const target = returnFocusTarget.current;',
      'returnFocusTarget.current = null;',
      "if (target?.isConnected && !target.matches(':disabled')) {",
      'event.preventDefault();',
      'target.focus();',
      'if (submitting.current || cleanupMutation.isPending) return;',
      'if (submitting.current || cleanupMutation.isPending || selectedStatuses.length === 0) return;',
      'await cleanupMutation.mutateAsync(selected);',
      'TERMINAL_OPTIONS.map(option => option.value)',
      "value: 'completed'", "value: 'failed'", "value: 'cancelled'",
      'onPointerDownOutside={event => event.preventDefault()}',
      'cleanupMutation.isPending || submitting.current) event.preventDefault()',
      'NAS 存储上的任何文件',
    ]) assert.ok(modal.includes(token), token);
    assert.ok(modal.indexOf('target.focus();') >
      modal.indexOf("if (target?.isConnected && !target.matches(':disabled')) {"));
    assert.doesNotMatch(modal, /<Dialog\\.Trigger/);
  });

  test('existing 32-case read-only Chromium Tasks matrix verifies Cancel, Enter, Escape and X', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "page.getByRole('button', { name: '清理历史' })",
      'const historyOpener = await historyLauncher.elementHandle();',
      "await history.getByRole('button', { name: '取消' }).click();",
      "await page.keyboard.press('Enter');",
      "await page.keyboard.press('Escape');",
      "await history.getByRole('button', { name: '关闭历史清理窗口' }).click();",
      'await page.waitForFunction(opener => document.activeElement === opener, historyOpener);',
      "assert.deepEqual(writes, [], 'Browser must not submit any mutating API request');",
      "request.method() !== 'GET'",
      'status: 405',
    ]) assert.ok(browser.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(opener => document.activeElement === opener, historyOpener);').length - 1, 3);
    assert.equal(browser.split("await page.keyboard.press('Enter');").length - 1 >= 3, true);
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(workflow.includes('node scripts/browser-task-overlays.mjs'));
    assert.ok(workflow.includes('Checkout exact candidate HEAD'));
    assert.ok(workflow.includes('Verify candidate identity'));
  });
});
