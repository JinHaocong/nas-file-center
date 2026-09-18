import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.4 page detail pass', () => {
  test('desktop shell keeps sidebar independent from the right content scroll container', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('/* v0.4.4 Page Detail Pass */'));
    assert.match(css, /\.nfc-app-shell\s*\{[^}]*height:\s*100dvh[^}]*overflow:\s*hidden/s);
    assert.match(css, /\.nfc-app-main\s*\{[^}]*height:\s*100dvh[^}]*overflow-y:\s*auto/s);
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar\s*\{[^}]*overflow:\s*hidden/s);
    assert.match(css, /\.nfc-sidebar-menu\s*\{[^}]*overflow-y:\s*auto/s);
  });

  test('mobile keeps native document scrolling and does not inherit the desktop scroll trap', () => {
    const css = read('src/index.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-app-shell\s*\{[^}]*height:\s*auto[^}]*overflow:\s*visible/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main\s*\{[^}]*height:\s*auto[^}]*overflow:\s*visible/s);
  });

  test('every primary right-side page owns a dedicated detail surface class', () => {
    const pages: Array<[string, string]> = [
      ['src/pages/Indexes/index.tsx', 'nfc-indexes-page'],
      ['src/pages/Scans/index.tsx', 'nfc-scans-page'],
      ['src/pages/PathMatch/index.tsx', 'nfc-path-match-page'],
      ['src/pages/Rename/index.tsx', 'nfc-rename-page'],
      ['src/pages/Batch/index.tsx', 'nfc-batch-page'],
      ['src/pages/Organizer/index.tsx', 'nfc-organizer-page'],
      ['src/pages/Workflows/WorkflowList.tsx', 'nfc-workflows-page'],
      ['src/pages/Plans/index.tsx', 'nfc-plans-page'],
      ['src/pages/Quarantine/index.tsx', 'nfc-quarantine-page'],
      ['src/pages/Tasks/index.tsx', 'nfc-tasks-page'],
      ['src/pages/Audit/index.tsx', 'nfc-audit-page'],
      ['src/pages/Settings/index.tsx', 'nfc-system-controls-page'],
    ];
    for (const [path, className] of pages) {
      assert.ok(read(path).includes(className), path);
    }
  });

  test('file-tool pages use a workbench treatment rather than a generic admin form card', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-path-match-page .nfc-file-tool-form'));
    assert.ok(css.includes('.nfc-rename-page .nfc-file-tool-form'));
    assert.ok(css.includes('.nfc-batch-page .nfc-file-tool-form'));
    assert.ok(css.includes('.nfc-tool-workbench'));
  });

  test('operations lists receive page-specific hierarchy rather than one universal table skin', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-indexes-page .nfc-data-panel',
      '.nfc-scans-page .nfc-data-panel',
      '.nfc-workflows-page .nfc-data-panel',
      '.nfc-plans-page .nfc-data-panel',
      '.nfc-tasks-page .nfc-data-panel',
      '.nfc-audit-page .nfc-data-panel',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
  });

  test('quarantine and settings keep destructive areas visually distinct from normal controls', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-quarantine-page .nfc-bulk-action-bar'));
    assert.ok(css.includes('.nfc-system-controls-page .nfc-settings-subpanel-danger'));
    assert.ok(css.includes('var(--nfc-danger-soft)'));
  });
});
