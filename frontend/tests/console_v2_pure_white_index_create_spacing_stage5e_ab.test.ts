import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const modal = read('src/pages/Indexes/index.tsx');
const css = read('src/styles/console-v2-indexes.css');
const browser = read('scripts/browser-indexes-ledger-states.mjs');

describe('Pure White Stage 5E-AB Index create modal visual gutter and focus', () => {
  test('owns content gutters instead of inheriting padding:0 from generic Dialog', () => {
    for (const token of [
      '.nfc-v2-index-form { display:grid;gap:12px;min-width:0;margin:0;padding:20px 24px 0; }',
      '.nfc-v2-index-form > .nfc-v2-confirm-actions {',
      'margin:6px -24px 0;',
      'padding:17px 24px 22px;',
      '.nfc-v2-index-form { padding:18px 18px 0; }',
      'margin-inline:-18px;',
      'padding:15px 18px 19px;',
      'width:min(96vw,640px);max-height:92dvh;',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/styles/console-v2.css').includes('padding: 0;'));
    assert.ok(modal.includes('className="nfc-v2-index-form"'));
  });

  test('read-only real Chromium checks field/picker/note gutters and header alignment across 32 cases', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "if (state === 'create' && b) {",
      'const gutter = width < 768 ? 16 : 22;',
      "['label', label]",
      "['directory picker', dialog.querySelector('.nfc-v2-index-form .nfc-v2-directory-picker')]",
      "['explanation', dialog.querySelector('.nfc-v2-index-form .nfc-form-note')]",
      'bounds.left >= b.left + gutter',
      'bounds.right <= b.right - gutter',
      'Math.abs(iconLeft - labelLeft) <= 2',
      "'create-dialog-' + label",
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(browser.includes(token), token);
  });

  test('controlled nested Dialog preserves exact launcher focus, safety and read-only mock', () => {
    for (const token of [
      'const createReturnFocusTarget = useRef<HTMLElement | null>(null);',
      'onOpenAutoFocus={() => {',
      'onCloseAutoFocus={event => {',
      "if (target?.isConnected && !target.matches(':disabled')) {",
      'createReturnFocusTarget.current = null;',
      'target.focus();',
      'createInFlight.current || createMutation.isPending',
      "const root = rootDraft.trim();",
      "if (!root.startsWith('/'))",
      "await createMutation.mutateAsync(root);",
      'const createOpener = await createLauncher.elementHandle();',
      'await page.waitForFunction(opener => document.activeElement === opener, createOpener);',
      "await create.getByRole('button', { name: '关闭索引窗口' }).click();",
      "await page.keyboard.press('Enter');",
      "'Nested picker must layer above create'",
      "request.method() !== 'GET'",
      'status: 405',
      "assert.deepEqual(writes, []",
      "assert.deepEqual(outbound, []",
    ]) assert.ok((token.startsWith('const createOpener') || token.startsWith('await page.') || token.startsWith('await create.') || token.startsWith("'Nested") ||
      token.startsWith("request.") || token.startsWith('status:') || token.startsWith('assert.deepEqual'))
      ? browser.includes(token) : modal.includes(token), token);
    assert.equal(browser.split('await page.waitForFunction(opener => document.activeElement === opener, createOpener);').length - 1, 2);
    assert.doesNotMatch(modal, /<Dialog\.Trigger/);
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(workflow.includes('node scripts/browser-indexes-ledger-states.mjs'));
    assert.ok(workflow.includes('Install and verify Chinese screenshot fonts'));
    assert.ok(workflow.includes('fonts-noto-cjk'));
    assert.ok(workflow.includes("fc-match -f '%{family}\\n' ':lang=zh-cn'"));
    assert.ok(workflow.indexOf('fonts-noto-cjk') <
      workflow.indexOf('node scripts/browser-indexes-ledger-states.mjs'));
    assert.ok(workflow.includes('Checkout exact candidate HEAD'));
  });
});
