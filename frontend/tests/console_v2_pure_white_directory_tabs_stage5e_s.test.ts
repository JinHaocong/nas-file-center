import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { DIRECTORY_TABS, nextDirectoryTab } from '../src/components/DirectoryPicker/tab_navigation';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Pure White Stage 5E-S directory tablist keyboard and ARIA', () => {
  test('left/right arrows wrap; Home/End jump; non-navigation keys preserve browser semantics', () => {
    assert.deepEqual(DIRECTORY_TABS, ['browser', 'favorites', 'recent']);
    assert.equal(nextDirectoryTab('browser', 'ArrowRight'), 'favorites');
    assert.equal(nextDirectoryTab('favorites', 'ArrowRight'), 'recent');
    assert.equal(nextDirectoryTab('recent', 'ArrowRight'), 'browser');
    assert.equal(nextDirectoryTab('browser', 'ArrowLeft'), 'recent');
    assert.equal(nextDirectoryTab('recent', 'ArrowLeft'), 'favorites');
    for (const tab of DIRECTORY_TABS) {
      assert.equal(nextDirectoryTab(tab, 'Home'), 'browser');
      assert.equal(nextDirectoryTab(tab, 'End'), 'recent');
      for (const key of ['Tab', 'Shift', 'Escape', 'Enter', ' ', 'ArrowDown', 'ArrowUp']) {
        assert.equal(nextDirectoryTab(tab, key), null, tab + ': ' + key);
      }
    }
  });

  test('only selected tab is a normal Tab stop and every aria-controls resolves to the stable panel', () => {
    const modal = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    assert.match(modal, /role="tablist" aria-label="目录来源"/);
    assert.match(modal, /ref=\{node => \{ tabRefs\.current\[tab\] = node; \}\}/);
    assert.match(modal, /tabIndex=\{activeTab === tab \? 0 : -1\}/);
    assert.match(modal, /aria-controls="nfc-directory-active-panel"/);
    assert.match(modal, /role="tabpanel" id="nfc-directory-active-panel"/);
    assert.match(modal, /aria-labelledby=\{'nfc-directory-tab-' \+ activeTab\}/);
    assert.match(modal, /tabIndex=\{0\} className="nfc-v2-directory-panel"/);
    assert.match(modal, /const next = nextDirectoryTab\(activeTab, event\.key\);/);
    assert.match(modal, /event\.preventDefault\(\);\s*setActiveTab\(next\);\s*tabRefs\.current\[next\]\?\.focus\(\);/);
    assert.match(modal, /if \(busy\) return;\s*const next = nextDirectoryTab/);
    assert.match(modal, /onClick=\{\(\) => setActiveTab\(tab\)\}/);
  });

  test('existing 32-case GET-only browser matrix checks arrows, roving focus and Tab into panel', () => {
    const runner = read('scripts/browser-indexes-ledger-states.mjs');
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    for (const needle of [
      "await page.keyboard.press('ArrowRight')",
      "await page.keyboard.press('ArrowLeft')",
      "await page.keyboard.press('Home')",
      "await page.keyboard.press('End')",
      "await page.keyboard.press('Tab')",
      "await checkTab('favorites')", "await checkTab('recent')",
      'Tab from selected tab must reach the active panel',
      '32/32 cases, 160 screenshots', 'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
    ]) assert.ok(runner.includes(needle), needle);
    assert.match(workflow, /node scripts\/browser-indexes-ledger-states\.mjs/);
  });

  test('directory authority, busy selection guard and nested close focus behavior are retained', () => {
    const modal = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    for (const needle of [
      'isWithinDirectoryRoots(path, allowedRoots)',
      'filesystemApi.recordRecent(paths)', 'selectionSession !== selectionSessionRef.current',
      'returnFocusTo?.isConnected',
      'onEscapeKeyDown={event => { if (busy || confirmFavoriteId !== null) event.preventDefault(); }}',
    ]) assert.ok(modal.includes(needle), needle);
  });
});
