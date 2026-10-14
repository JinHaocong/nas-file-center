import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Pure White Stage 5E-P keyboard focus after DirectoryPicker nested dialogs', () => {
  test('each native launcher snapshots its own focus target, not a stale global button', () => {
    const picker = read('src/components/DirectoryPicker/DirectoryPicker.tsx');
    const types = read('src/components/DirectoryPicker/types.ts');
    assert.match(picker, /returnFocusTarget = useRef<HTMLButtonElement \| null>\(null\)/);
    assert.match(picker, /if \(disabled\) return;[\s\S]*?returnFocusTarget.current = button;/);
    assert.equal(picker.match(/onClick=\{event => openDirectoryBrowser\(event.currentTarget\)\}/g)?.length, 3);
    assert.match(picker, /returnFocusTo=\{returnFocusTarget.current\}/);
    assert.match(types, /returnFocusTo\?: HTMLElement \| null/);
  });

  test('Radix closes to the mounted enabled launcher, never overriding unsafe/unmounted target', () => {
    const modal = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    assert.match(modal, /onCloseAutoFocus=\{event => \{/);
    assert.match(modal, /returnFocusTo\?\.isConnected && !returnFocusTo\.matches\(':disabled'\)/);
    assert.match(modal, /event\.preventDefault\(\);\s*returnFocusTo\.focus\(\)/);
    assert.match(modal, /onEscapeKeyDown=\{event => \{ if \(busy \|\| confirmFavoriteId !== null\) event\.preventDefault\(\); \}\}/);
    assert.match(modal, /isWithinDirectoryRoots\(path, allowedRoots\)/);
  });

  test('the exact-HEAD read-only Chromium matrix checks Escape, focus return, Enter and Tab trap', () => {
    const runner = read('scripts/browser-indexes-ledger-states.mjs');
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    for (const token of [
      'focusedLauncher', "page.keyboard.press('Enter')", "page.keyboard.press('Tab')",
      'Nested picker must trap keyboard Tab within the active dialog',
      "page.waitForFunction(focusedLauncher", 'Keyboard reopening must preserve parent dialog',
      '32/32 cases, 160 screenshots', "request.method() !== 'GET'",
      'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
    ]) assert.ok(runner.includes(token), token);
    assert.match(workflow, /node scripts\/browser-indexes-ledger-states\.mjs/);
  });
});
