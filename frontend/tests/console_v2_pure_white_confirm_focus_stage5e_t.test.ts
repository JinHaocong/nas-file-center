import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const confirm = read('src/components/ui/ConsoleConfirmDialog.tsx');
const browser = read('scripts/browser-task-overlays.mjs');

describe('Pure White Stage 5E-T controlled confirm focus return', () => {
  test('capture the real opener before Radix autofocus for dialogs without Dialog.Trigger', () => {
    assert.match(confirm, /returnFocusTarget = React\.useRef<HTMLElement \| null>\(null\)/);
    assert.match(confirm, /onOpenAutoFocus=\{\(\) => \{/);
    assert.match(confirm, /const active = document\.activeElement;/);
    assert.match(confirm, /active instanceof HTMLElement && active !== document\.body/);
    assert.match(confirm, /returnFocusTarget\.current = active/);
    assert.doesNotMatch(confirm, /<Dialog\.Trigger/);
  });

  test('restore only a mounted enabled launcher without overriding unsafe fallbacks', () => {
    for (const token of [
      'onCloseAutoFocus={event => {',
      'const target = returnFocusTarget.current;',
      'returnFocusTarget.current = null;',
      "target?.isConnected && !target.matches(':disabled')",
      '!target.closest(\'[aria-disabled="true"], [inert], [hidden]\')',
      'event.preventDefault();',
      'target.focus();',
      'if (!busy) onOpenChange(next);',
      'disabled={busy || disabled} loading={busy}',
      'if (!busy && !disabled) onConfirm();',
    ]) assert.ok(confirm.includes(token), token);
  });

  test('existing 32-case read-only Chromium Tasks matrix checks Escape, Enter, Cancel and restored focus', () => {
    for (const token of [
      "const deleteLauncher = sheet.getByRole('button', { name: '删除任务 #42' });",
      "await page.keyboard.press('Escape');",
      'const launcherFocused = () =>',
      "await page.keyboard.press('Enter');",
      "await confirm.getByRole('button', { name: '取消' }).click();",
      'await page.waitForFunction(launcherFocused);',
      'await sheet.waitFor({ state: \'visible\' });',
      "request.method() !== 'GET'",
      "assert.deepEqual(writes, []",
      '32/32 theme-viewport cases, 64 actual dialog screenshots',
    ]) assert.ok(browser.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(launcherFocused);').length - 1, 2);
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(workflow.includes('node scripts/browser-task-overlays.mjs'));
  });
});
