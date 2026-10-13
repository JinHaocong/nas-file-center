import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed v050/v051/v055 legacy CSS retirement', () => {
  const sheets = [
    'src/styles/v050-layout.css',
    'src/styles/v051-product-polish.css',
    'src/styles/v055-workspace-breathing.css',
  ];

  test('all three legacy sheets contain zero AntD or anticon selectors', () => {
    for (const path of sheets) {
      const css = read(path);
      assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/, path);
      assert.match(css, /@media /);
      assert.ok(css.length > 9000, path + ' native structural rules must remain');
    }
  });

  test('v050 maintains native dashboard, operational and responsive layouts', () => {
    const css = read(sheets[0]);
    for (const marker of [
      '.nfc-dashboard-command-deck {', '.nfc-dashboard-page .nfc-dashboard-layout {',
      '.nfc-quarantine-command-center {', '.nfc-tasks-page .nfc-filter-bar {',
      '.nfc-plans-page > .nfc-data-panel {', '.nfc-system-controls-page .nfc-settings-grid {',
      '.nfc-page-content {', '@media (max-width: 767px)',
    ]) assert.ok(css.includes(marker), marker);
  });

  test('v051 keeps keyboard row-actions, mobile cards and native overlay structure', () => {
    const css = read(sheets[1]);
    assert.match(css, /\.nfc-row-actions\s*\{[^}]*opacity:\s*0\.72/);
    assert.match(css, /\.nfc-row-actions:focus-within\s*\{[^}]*opacity:\s*1/);
    for (const marker of [
      '.nfc-centered-state', '.nfc-file-tool-form .nfc-form-grid {',
      '.nfc-batch-page .nfc-batch-operation-grid {',
      '.nfc-mobile-record-actions {', '.nfc-drawer-title {',
      '.nfc-overlay-stack {', '@media (max-width: 767px)',
    ]) assert.ok(css.includes(marker), marker);
  });

  test('v055 retains wide workspace, responsive gutters and native header controls', () => {
    const css = read(sheets[2]);
    for (const marker of [
      '--nfc-v55-page-gutter:', '.nfc-app-main .nfc-page-content {',
      '.nfc-app-main .nfc-page-header {', '.nfc-app-main .nfc-page-actions {',
      '.nfc-app-main .nfc-page-actions .nfc-action-bar {',
      '@media (min-width: 1800px)', '@media (max-width: 767px)',
    ]) assert.ok(css.includes(marker), marker);
  });

  test('cascade order is stable and CI checks all 51 owned/reviewed files', () => {
    const main = read('src/main.tsx');
    let previous = main.indexOf("import './styles/v048.css';");
    assert.ok(previous >= 0);
    for (const sheet of [
      'v050-layout.css', 'v051-product-polish.css',
      'v055-workspace-breathing.css', 'v056-right-workspace-v2.css',
    ]) {
      const idx = main.indexOf("import './styles/" + sheet + "';");
      assert.ok(idx > previous, sheet);
      previous = idx;
    }
    assert.ok(main.indexOf("import './styles/console-v2.css';") > previous);
    const guard = read('scripts/check-console-css-ownership.mjs');
    for (const sheet of sheets) {
      assert.ok(guard.includes("'legacy-reviewed:" + sheet.split('/').at(-1) + "'"));
    }
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
  });
});
