import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const dialog = read('src/components/dedupe/DedupeActionDialog.tsx');
const page = read('src/pages/Scans/AdvancedDedupePage.tsx');
const browser = read('scripts/browser-organizer-dedupe-overlays.mjs');

describe('Pure White Stage 5E-Y direct advanced Dedupe dialog focus return', () => {
  test('controlled Radix dialog captures actual opener before focus trap, without a Dialog.Trigger', () => {
    for (const token of [
      'const returnFocusTarget = React.useRef<HTMLElement | null>(null);',
      'onOpenAutoFocus={() => {',
      'const active = document.activeElement;',
      'active instanceof HTMLElement && active !== document.body',
      'returnFocusTarget.current = active',
      '<Dialog.Root open={kind !== null}',
    ]) assert.ok(dialog.includes(token), token);
    assert.doesNotMatch(dialog, /<Dialog\.Trigger/);
  });

  test('focus is restored only to connected, enabled launcher; busy and digest authority unchanged', () => {
    for (const token of [
      'onCloseAutoFocus={event => {',
      'const target = returnFocusTarget.current;',
      'returnFocusTarget.current = null;',
      "if (target?.isConnected && !target.matches(':disabled')) {",
      'event.preventDefault();',
      'target.focus();',
      'const cancelSafely = () => { if (!busy) onCancel(); };',
      'const confirmSafely = () => { if (!busy && kind !== null) onConfirm(); };',
      'onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}',
      'onPointerDownOutside={event => event.preventDefault()}',
      'disabled={!kind || busy}',
      "kind !== 'generate' && errorMessage",
      'Hardlink 后两个路径共享同一个 inode',
      'Reflink 使用独立 inode',
    ]) assert.ok(dialog.includes(token), token);
    for (const token of [
      '!canGeneratePlan(dedupeState)', 'generateInFlight.current',
      'expected_preview_digest: dedupeState.acceptedPreviewDigest',
      "scansApi.createAdvancedDedupePlan(scanId",
    ]) assert.ok(page.includes(token), token);
    assert.doesNotMatch(dialog, /createAdvancedDedupePlan\(|executePlan\(/);
  });

  test('32 actual Chromium matrix cases assert Cancel/Enter/Escape return to the direct launcher without Draft writes', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "url.pathname === '/api/scans/501/dedupe-preview'",
      "request.method() === 'POST'",
      "await page.goto(BASE_URL + '/scans/501/dedupe'",
      "page.getByRole('button', { name: '生成执行计划草案' })",
      'const generateOpener = await generateLauncher.elementHandle();',
      "await directDialog.getByRole('button', { name: '取消' }).click();",
      "await page.keyboard.press('Enter');",
      "await page.keyboard.press('Escape');",
      'await page.waitForFunction(opener => document.activeElement === opener, generateOpener);',
      'assert.deepEqual(forbidden, []',
      'assert.deepEqual(external, []',
      'No Draft/Generate/Execute/Save/Delete API allowed',
    ]) assert.ok(browser.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(opener => document.activeElement === opener, generateOpener);').length - 1, 2);
    const ci = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(ci.includes('node scripts/browser-organizer-dedupe-overlays.mjs'));
    assert.ok(ci.includes('Checkout exact candidate HEAD'));
    assert.ok(ci.includes('Verify candidate identity'));
  });
});
