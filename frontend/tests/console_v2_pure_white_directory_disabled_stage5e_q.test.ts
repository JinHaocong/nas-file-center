import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Pure White Stage 5E-Q DirectoryPicker fail-closed disabled transition', () => {
  test('a busy caller dismisses the shared browser and blocks stale onChange', () => {
    const picker = source('src/components/DirectoryPicker/DirectoryPicker.tsx');
    assert.match(picker, /disabledRef\.current = disabled/);
    assert.match(picker, /useEffect\(\(\) => \{\s*if \(disabled\) setModalOpen\(false\);\s*\}, \[disabled\]\)/);
    assert.match(picker, /const handleModalConfirm = \(selected: string \| string\[\]\) => \{\s*if \(disabledRef\.current\) return;/);
    assert.match(picker, /open=\{modalOpen && !disabled\}/);
    assert.match(picker, /disabled=\{disabled\}/);
    assert.match(picker, /returnFocusTo=\{returnFocusTarget\.current\}/);
    assert.match(picker, /onClick=\{event => openDirectoryBrowser\(event\.currentTarget\)\}/);
  });

  test('the async recents wait cannot publish to a disabled, closed or reopened picker', () => {
    const modal = source('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    const types = source('src/components/DirectoryPicker/types.ts');
    assert.match(types, /disabled\?: boolean;/);
    assert.match(modal, /disabled = false/);
    assert.match(modal, /<Dialog.Root open=\{open && !disabled\}/);
    assert.match(modal, /const selectionSessionRef = useRef\(0\)/);
    assert.match(modal, /selectionSessionRef\.current \+= 1;/);
    assert.match(modal, /\[open, disabled, initialPath, selectedValues, multiple\]/);
    assert.match(modal, /if \(disabledRef\.current \|\| !openRef\.current \|\| confirmingRef\.current \|\|/);
    assert.match(modal, /const selectionSession = selectionSessionRef\.current;/);
    assert.match(modal, /await filesystemApi\.recordRecent\(paths\)\.catch\(\(\) => \{\}\);[\s\S]*?if \(disabledRef\.current \|\| !openRef\.current \|\|[\s\S]*?selectionSession !== selectionSessionRef\.current\) return;\s*onConfirm\(selection\);/);
    assert.match(modal, /isWithinDirectoryRoots\(path, allowedRoots\)/);
  });

  test('does not change NAS path authority or form mutation semantics', () => {
    const browser = source('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    const picker = source('src/components/DirectoryPicker/DirectoryPicker.tsx');
    const scan = source('src/components/scans/ScanCreateModal.tsx');
    const indexes = source('src/pages/Indexes/index.tsx');
    assert.match(browser, /filesystemApi\.listDirectory\(/);
    assert.match(browser, /resolveDirectorySelection\(selectedPaths, effectiveCurrentPath, multiple\)/);
    assert.match(browser, /onCloseAutoFocus=\{event => \{/);
    assert.match(picker, /onChange\?\.\(Array\.isArray\(selected\) \? selected\[0\] \|\| '' : selected\)/);
    assert.match(scan, /toScanCreatePayload\(values\)/);
    assert.match(indexes, /indexesApi\.createIndex\(root\)/);
    const workflow = source('../.github/workflows/ui-v044-validation.yml');
    assert.match(workflow, /node scripts\/browser-indexes-ledger-states\.mjs/);
  });
});
