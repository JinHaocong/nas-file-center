import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed v056 right workspace CSS retirement', () => {
  const css = read('src/styles/v056-right-workspace-v2.css');

  test('retired AntD selectors are absent while native workspace styles remain', () => {
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 48000, 'retain native workspace rules and cascade');
  });

  test('mixed selectors retain keyboard focus and responsive ledger width', () => {
    assert.match(css, /\.nfc-row-actions\s*\{[^}]*opacity:\s*0\.56;/);
    assert.match(css, /\.nfc-row-actions:focus-within\s*\{[^}]*opacity:\s*1;/);
    assert.match(css, /\.nfc-app-main \.nfc-page-layout-ledger \.nfc-data-panel-body\s*\{\s*width:\s*100%;\s*min-width:\s*0;/);
  });

  test('shell card contracts retain only native panels and mobile metric card', () => {
    assert.match(css, /\.nfc-app-main \.nfc-data-panel,[\s\S]*?\.nfc-app-main \.nfc-responsive-descriptions\s*\{[^}]*border:\s*1px solid var\(--nfc-shell-card-border\) !important;[^}]*box-shadow:\s*var\(--nfc-shell-card-shadow\) !important;/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*?\.nfc-app-main \.nfc-responsive-descriptions,\s*\.nfc-app-main \.nfc-metric-card\s*\{[^}]*box-shadow:\s*none !important;/);
  });

  test('native workbench, empty-state neighborhood and diagnostic layouts survive', () => {
    for (const selector of [
      '.nfc-app-main .nfc-page-layout-ledger > .nfc-data-panel > .nfc-data-panel-header {',
      '.nfc-app-main .nfc-page-layout-ledger .nfc-data-panel-body {',
      '.nfc-dashboard-page .nfc-dashboard-rail .nfc-data-panel-body {',
      '.nfc-dedupe-diagnostic-path-grid,',
      '.nfc-dedupe-diagnostic-section-heading {',
    ]) assert.ok(css.includes(selector), selector);
    assert.match(css, /\.nfc-app-main \.nfc-page-layout-ledger > \.nfc-data-panel > \.nfc-data-panel-header\s*\{[^}]*padding:\s*var\(--nfc-w2-panel-header-top\)/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-dedupe-diagnostic-path-grid,\s*\.nfc-dedupe-diagnostic-scan-grid\s*\{\s*grid-template-columns:\s*1fr;/);
    assert.match(css, /@media \(min-width: 768px\)/);
  });

  test('right-workspace visual tests no longer require unreachable AntD DOM', () => {
    const source = read('tests/right_workspace_v2.test.ts');
    assert.doesNotMatch(source, /\\\.ant-[a-z]/);
    assert.match(source, /nfc-v2-dialog-overlay/);
    assert.match(source, /nfc-v2-dialog-footer/);
    assert.match(source, /nfc-responsive-descriptions/);
  });

  test('CSS import order, guard coverage and compiled test registration remain', () => {
    const main = read('src/main.tsx');
    const before = main.indexOf("import './styles/v055-workspace-breathing.css';");
    const current = main.indexOf("import './styles/v056-right-workspace-v2.css';");
    const settings = main.indexOf("import './styles/pages/settings.css';");
    const native = main.indexOf("import './styles/console-v2.css';");
    assert.ok(before >= 0 && before < current && current < settings && settings < native);
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v056-right-workspace-v2.css'"));
    assert.ok(guard.includes('if (errors.length) process.exitCode = 1'));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_v056_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_v056_css.test.js'));
  });
});
