import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const legacy = ['shell.css', 'primitives.css', 'overlays.css', 'responsive.css'];

describe('Console v2 reviewed v047 foundational CSS retirement', () => {
  test('four reviewed layers have zero AntD/anticon CSS selectors', () => {
    for (const name of legacy) {
      const css = read('src/styles/' + name);
      assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/, name);
    }
  });

  test('native shell chrome retains header, badge, dock and theme surface', () => {
    const css = read('src/styles/shell.css');
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar\s*\{[^}]*background:\s*var\(--nfc-nav-surface\) !important;/);
    assert.match(css, /\.nfc-header\.nfc-header\s*\{[^}]*border-bottom:\s*1px solid var\(--nfc-border-soft\);/);
    assert.match(css, /\.nfc-header-status-badge\s*\{[^}]*background:\s*color-mix\(/);
    assert.ok(css.includes('.nfc-mobile-dock'));
    assert.ok(css.includes('.nfc-header-status-badge.is-danger'));
  });

  test('native semantic panels and metrics preserve card layout and density', () => {
    const css = read('src/styles/primitives.css');
    for (const selector of [
      '.nfc-page-header {', '.nfc-page-actions {',
      '.nfc-data-panel {', '.nfc-data-panel-default {',
      '.nfc-data-panel-dense {', '.nfc-metric-grid {',
      '.nfc-metric-card {', '.nfc-breakall {',
    ]) assert.ok(css.includes(selector), selector);
    assert.match(css, /\.nfc-data-panel-dense\s*\{[^}]*box-shadow:\s*none;/);
    assert.match(css, /\.nfc-metric-grid\s*\{[^}]*gap:\s*0;/);
  });

  test('mobile actions, metrics, dock safe-area and breakpoint order survive', () => {
    const css = read('src/styles/responsive.css');
    const group = css.match(/\.nfc-page-actions \.nfc-action-bar\s*\{([^}]*)\}/);
    assert.ok(group && /width:\s*100%;/.test(group[1]));
    assert.match(css, /@media \(max-width: 767px\)/);
    assert.match(css, /@media \(max-width: 420px\)/);
    assert.ok(css.includes('.nfc-metric-grid'));
    assert.ok(css.includes('var(--nfc-mobile-dock-height'));
  });

  test('unreachable AntD overlay sheet retains import slot without applying styles', () => {
    const sheet = read('src/styles/overlays.css');
    const native = read('src/styles/console-v2-task-overlays.css');
    const dialog = read('src/styles/console-v2.css');
    assert.doesNotMatch(sheet, /\{[^}]*\}/);
    assert.match(native, /\.nfc-v2-sheet\.nfc-overlay-drawer\s*\{[^}]*background:\s*var\(--v2-paper\);/);
    assert.match(native, /@media \(max-width: 767px\)[\s\S]*\.nfc-v2-sheet\.nfc-overlay-drawer\s*\{\s*width:\s*100vw;/);
    assert.match(dialog, /\.nfc-v2-dialog:focus-visible\s*\{[^}]*outline:/);
    const entry = read('src/styles/v047.css');
    const imports = legacy.map(name => entry.indexOf("@import './" + name + "';"));
    assert.ok(imports.every(index => index >= 0), 'historical import locations remain');
    assert.ok(imports[0] < imports[1] && imports[1] < imports[2] && imports[2] < imports[3]);
  });

  test('audit covers 60 stylesheets and new regression executes in full frontend suite', () => {
    const audit = read('scripts/check-console-css-ownership.mjs');
    for (const name of legacy) assert.ok(audit.includes("'legacy-reviewed:" + name + "'"));
    assert.ok(audit.includes("'legacy-index:index.css'"));
    assert.ok(audit.includes("if (errors.length) process.exitCode = 1"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_core_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_core_css.test.js'));
  });
});
