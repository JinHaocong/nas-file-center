import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const scan = read('src/components/scans/ScanCreateModal.tsx');
const browser = read('scripts/browser-overlay-smoke.mjs');

describe('Pure White Stage 5E-W Scan Create controlled modal focus return', () => {
  test('remember the real opener before Radix autofocus without adding a fake Dialog.Trigger', () => {
    for (const token of [
      'const returnFocusTarget = useRef<HTMLElement | null>(null);',
      'onOpenAutoFocus={() => {',
      'const active = document.activeElement;',
      'active instanceof HTMLElement && active !== document.body',
      'returnFocusTarget.current = active',
      '<Dialog.Root open={open} onOpenChange={next => { if (!next) close(); }}>',
    ]) assert.ok(scan.includes(token), token);
    assert.doesNotMatch(scan, /<Dialog\.Trigger/);
  });

  test('only restore a still-connected enabled opener; never change request authority or busy guards', () => {
    for (const token of [
      'onCloseAutoFocus={event => {',
      'const target = returnFocusTarget.current;',
      'returnFocusTarget.current = null;',
      "if (target?.isConnected && !target.matches(':disabled')) {",
      'event.preventDefault();', 'target.focus();',
      'if (createMutation.isPending || submitting.current) return;',
      'await createMutation.mutateAsync(payload);',
      'onEscapeKeyDown={event => { if (createMutation.isPending || submitting.current) event.preventDefault(); }}',
      'onPointerDownOutside={event => event.preventDefault()}',
      "navigate('/scans/' + res.scan_job_id)",
    ]) assert.ok(scan.includes(token), token);
    assert.equal(scan.indexOf('target.focus();') > scan.indexOf("if (target?.isConnected && !target.matches(':disabled')) {"), true);
    assert.doesNotMatch(scan, /createMutation\.mutate\(/);
  });

  test('existing nested DirectoryPicker Chromium matrix asserts Close/Enter/Escape focus restoration on 32 cases', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "const scanLauncher = page.getByRole('button', { name: '新建扫描' }).first();",
      'const scanOpener = await scanLauncher.elementHandle();',
      "await scanModal.getByRole('button', { name: '关闭新建扫描' }).click();",
      "await page.keyboard.press('Enter');",
      "await page.keyboard.press('Escape');",
      'await page.waitForFunction(opener => document.activeElement === opener, scanOpener);',
      'await scanModal.waitFor({ state: \'visible\' });',
      'assert.deepEqual(deniedMethods, []',
      "request.method() !== 'GET'",
    ]) assert.ok(browser.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(opener => document.activeElement === opener, scanOpener);').length - 1, 2);
    const ci = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(ci.includes('node scripts/browser-overlay-smoke.mjs'));
    assert.ok(ci.includes('Checkout exact candidate HEAD'));
    assert.ok(ci.includes('Verify candidate identity'));
  });
});
