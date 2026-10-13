import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed historical component CSS retirement', () => {
  const css = read('src/styles/components.css');

  test('removes obsolete AntD and anticon selectors without losing native styles', () => {
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 17000, 'retain native component and diagnostic rules');
  });

  test('preserves directory picker, breadcrumb, selection and keyboard-adjacent classes', () => {
    for (const selector of [
      '.nfc-directory-picker-title {',
      '.nfc-directory-picker-body {',
      '.nfc-directory-browser-row {',
      '.nfc-path-breadcrumb {',
      '.nfc-path-breadcrumb-current {',
      '.nfc-directory-list-viewport {',
      '.nfc-directory-item-name {',
      '.nfc-directory-picker-footer-actions {',
    ]) assert.ok(css.includes(selector), selector);
    assert.match(css, /\.nfc-directory-picker-footer\s*\{[^}]*display:\s*flex;/);
  });

  test('keeps the native embedded table from the former mixed selector', () => {
    assert.match(css, /\.nfc-overlay-section-flush > \.nfc-embedded-table\s*\{\s*margin:\s*0;/);
    assert.doesNotMatch(css, /\.nfc-overlay-section-flush > \.ant-table-wrapper/);
    assert.ok(css.includes('.nfc-quarantine-preview-card {'));
    assert.ok(css.includes('.nfc-quarantine-descriptions,'));
  });

  test('preserves task status, dedupe controls and responsive diagnostic geometry', () => {
    for (const selector of [
      '.nfc-task-progress {',
      '.nfc-task-progress-meta {',
      '.nfc-task-progress-success .nfc-task-progress-status {',
      '.nfc-task-progress-danger .nfc-task-progress-status {',
      '.nfc-dedupe-summary-grid {',
      '.nfc-dedupe-rule-row {',
      '.nfc-dedupe-root-release-panel {',
      '.nfc-dedupe-scorer-editor,',
    ]) assert.ok(css.includes(selector), selector);
    assert.ok(css.includes('@media (max-width: 1199px)'));
    assert.ok(css.includes('@media (max-width: 900px)'));
    assert.ok(css.includes('@media (max-width: 767px)'));
  });

  test('eight additional already-native CSS files become explicitly audited', () => {
    const guard = read('scripts/check-console-css-ownership.mjs');
    for (const path of [
      'components.css', 'foundation.css', 'pages/dashboard.css',
      'pages/details.css', 'pages/operations.css', 'pages/scheduler.css',
      'tokens.css', 'v046.css', 'v047.css',
    ]) {
      assert.ok(guard.includes("'legacy-reviewed:" + path + "'"), path);
      assert.doesNotMatch(read('src/styles/' + path), /\.(?:ant-[a-z][\w-]*|anticon\b)/, path);
    }
    assert.ok(guard.includes('if (errors.length) process.exitCode = 1'));
  });

  test('v047 cascade position and full frontend test registration are unchanged', () => {
    const imports = read('src/styles/v047.css');
    assert.ok(imports.indexOf("@import './overlays.css';") <
      imports.indexOf("@import './components.css';"));
    assert.ok(imports.indexOf("@import './components.css';") <
      imports.indexOf("@import './responsive.css';"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_components_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_components_css.test.js'));
  });
});
