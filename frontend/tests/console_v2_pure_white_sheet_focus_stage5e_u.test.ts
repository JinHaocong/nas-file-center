import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const sheet = read('src/components/ui/ConsoleSheet.tsx');
const browser = read('scripts/browser-task-overlays.mjs');

describe('Pure White Stage 5E-U controlled Sheet focus recovery', () => {
  test('captures the actual opener before Radix autofocus; retains controlled close and semantics', () => {
    for (const token of [
      'const returnFocusTarget = React.useRef<HTMLElement | null>(null);',
      'onOpenAutoFocus={() => {', 'const active = document.activeElement;',
      'active instanceof HTMLElement && active !== document.body',
      'returnFocusTarget.current = active',
      '<Dialog.Root open={open} onOpenChange={next => { if (!next) onClose(); }}>',
      '<Dialog.Close asChild>', 'aria-label="关闭详情抽屉"',
    ]) assert.ok(sheet.includes(token), token);
    assert.doesNotMatch(sheet, /<Dialog\.Trigger/);
  });

  test('restores focus only to live enabled launcher; otherwise leaves Radix fallback', () => {
    for (const token of [
      'onCloseAutoFocus={event => {', 'const target = returnFocusTarget.current;',
      'returnFocusTarget.current = null;',
      "if (target?.isConnected && !target.matches(':disabled')) {",
      'event.preventDefault();', 'target.focus();',
    ]) assert.ok(sheet.includes(token), token);
    assert.ok(sheet.indexOf('target.focus();') > sheet.indexOf("if (target?.isConnected && !target.matches(':disabled')) {"));
    assert.ok(sheet.indexOf('event.preventDefault();') > sheet.indexOf('onCloseAutoFocus={event => {'));
  });

  test('read-only Tasks 32-case matrix checks Close, Enter reopen, Escape and exact focus return', () => {
    for (const token of [
      "const detailLauncher = page.getByRole('button', { name: '详情' }).first();",
      'const detailOpener = await detailLauncher.elementHandle();',
      "await page.getByRole('button', { name: '关闭详情抽屉' }).click();",
      "await page.keyboard.press('Enter');", "await page.keyboard.press('Escape');",
      'await page.waitForFunction(opener => document.activeElement === opener, detailOpener);',
      'await sheet.waitFor({ state: \'visible\' });',
      "const deleteLauncher = sheet.getByRole('button', { name: '删除任务 #42' });",
      'assert.deepEqual(writes, []',
      '32/32 theme-viewport cases, 64 actual dialog screenshots',
    ]) assert.ok(browser.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(opener => document.activeElement === opener, detailOpener);').length - 1, 2);
    assert.ok(browser.includes("request.method() !== 'GET'"));
    assert.ok(read('../.github/workflows/ui-v044-validation.yml').includes('node scripts/browser-task-overlays.mjs'));
  });
});
