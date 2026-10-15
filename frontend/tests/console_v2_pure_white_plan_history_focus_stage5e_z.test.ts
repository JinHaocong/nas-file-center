import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const modal = read('src/components/plans/PlanHistoryCleanupModal.tsx');
const browser = read('scripts/browser-plan-lifecycle-overlays.mjs');

describe('Pure White Stage 5E-Z Plan History cleanup controlled dialog focus return', () => {
  test('retains the actual keyboard opener before Radix auto-focus without an artificial Trigger', () => {
    for (const token of [
      'const returnFocusTarget = useRef<HTMLElement | null>(null);',
      'onOpenAutoFocus={() => {',
      'const active = document.activeElement;',
      'active instanceof HTMLElement && active !== document.body',
      'returnFocusTarget.current = active',
      '<Dialog.Root open={open}',
      '<ConsoleButton leadingIcon={<ConsoleIcon name="trash" size={16} />}',
    ]) assert.ok(modal.includes(token), token);
    assert.doesNotMatch(modal, /<Dialog\.Trigger/);
  });

  test('returns focus only to connected enabled launcher; preserves terminal whitelist and single-flight safeguards', () => {
    for (const token of [
      'onCloseAutoFocus={event => {',
      'const target = returnFocusTarget.current;',
      'returnFocusTarget.current = null;',
      "if (target?.isConnected && !target.matches(':disabled')) {",
      'event.preventDefault();',
      'target.focus();',
      'if (submitting.current || cleanupMutation.isPending) return;',
      'if (submitting.current || selectedStatuses.length === 0) return;',
      'await cleanupMutation.mutateAsync(selected);',
      'PLAN_HISTORY_OPTIONS.map(x => x.value)',
      ".filter(x => selectedStatuses.includes(x))",
      "value: 'completed'", "value: 'failed'",
      'onPointerDownOutside={event => event.preventDefault()}',
      'cleanupMutation.isPending || submitting.current) event.preventDefault()',
      'NAS 存储上的任何文件',
    ]) assert.ok(modal.includes(token), token);
    assert.doesNotMatch(modal, /<Dialog\.Close/);
    assert.equal(modal.indexOf('target.focus();') > modal.indexOf("if (target?.isConnected && !target.matches(':disabled')) {"), true);
  });

  test('read-only Chromium 32-case Plan lifecycle matrix tests Cancel, Enter, Escape and X focus return', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "await page.goto(BASE_URL + '/plans', { waitUntil: 'domcontentloaded' });",
      "page.getByRole('button', { name: '清理计划历史' }).first()",
      "const historyOpener = await historyLauncher.elementHandle();",
      "await historyDialog.getByRole('button', { name: '取消' }).click();",
      "await page.keyboard.press('Enter');",
      "await page.keyboard.press('Escape');",
      "await historyDialog.getByRole('button', { name: '关闭清理窗口' }).click();",
      'await page.waitForFunction(opener => document.activeElement === opener, historyOpener);',
      'assert.deepEqual(forbidden, []',
      'No Plan or History cleanup mutations allowed',
      'assert.deepEqual(external, []',
      "url.pathname === '/api/plans/104/rebuild-preview'",
    ]) assert.ok(browser.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(opener => document.activeElement === opener, historyOpener);').length - 1, 3);
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(workflow.includes('node scripts/browser-plan-lifecycle-overlays.mjs'));
    assert.ok(workflow.includes('Checkout exact candidate HEAD'));
    assert.ok(workflow.includes('Verify candidate identity'));
  });
});
