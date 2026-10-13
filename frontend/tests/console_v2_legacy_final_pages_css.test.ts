import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const styles = [
  'pages/login.css', 'pages/organizer.css', 'pages/tools.css',
  'pages/workflows.css', 'v048-pages.css',
];

describe('Console v2 final historical page-layer CSS retirement', () => {
  test('all five remaining page styles are zero AntD selectors', () => {
    for (const path of styles) {
      const css = read('src/styles/' + path);
      assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/, path);
      assert.ok(css.length > 1000, 'preserve native page composition: ' + path);
    }
  });

  test('native login geometry, mobile layout and dark theme remain', () => {
    const css = read('src/styles/pages/login.css');
    assert.match(css, /\.nfc-login-panel\s*\{[^}]*width:\s*min\(432px,\s*100%\)/);
    assert.match(css, /\[data-theme='dark'\] \.nfc-login-panel\s*\{[^}]*box-shadow:/);
    assert.match(css, /@media \(max-width: 767px\)/);
    assert.ok(css.includes('.nfc-login-submit {'));
    assert.ok(css.includes('.nfc-login-security-note {'));
  });

  test('native organizer preview, mobile cards and mixed dark-theme selectors remain', () => {
    const css = read('src/styles/pages/organizer.css');
    assert.ok(css.includes('.nfc-organizer-advanced-collapse {'));
    assert.ok(css.includes('.nfc-organizer-preview-digest code {'));
    assert.match(css, /\[data-theme='dark'\] \.nfc-organizer-advanced-collapse,\s*\[data-theme='dark'\] \.nfc-organizer-preview-digest\s*\{[^}]*border-color:/);
    assert.ok(css.includes('.nfc-organizer-step-import-row {'));
    assert.ok(css.includes('@media (max-width: 767px)'));
  });

  test('native tool workbenches, file forms and mobile surfaces remain', () => {
    const css = read('src/styles/pages/tools.css');
    assert.ok(css.includes('.nfc-path-match-page .nfc-tool-workbench,'));
    assert.ok(css.includes('.nfc-file-tool-form .nfc-form-grid {'));
    assert.ok(css.includes('.nfc-file-tool-primary-actions {'));
    assert.ok(css.includes('.nfc-batch-page .nfc-batch-operation-grid {'));
    assert.ok(css.includes('@media (max-width: 767px)'));
  });

  test('native workflow editors and premium dedupe surfaces retain responsive styling', () => {
    const workflow = read('src/styles/pages/workflows.css');
    const premium = read('src/styles/v048-pages.css');
    for (const name of [
      '.nfc-workflow-step-card {', '.nfc-step-add-surface {',
      '.nfc-completed-scan-picker {', '.nfc-filter-group-card,',
    ]) assert.ok(workflow.includes(name), name);
    assert.ok(workflow.includes('@media (max-width: 900px)'));
    assert.ok(workflow.includes('@media (max-width: 767px)'));
    assert.match(premium, /\.nfc-workflow-builder-page \.nfc-dedupe-surface-card,\s*\.nfc-workflow-builder-page \.nfc-dedupe-config-card,\s*\.nfc-workflow-builder-page \.nfc-dedupe-summary-metric,\s*\.nfc-workflow-builder-page \.nfc-dedupe-root-release-panel\s*\{[^}]*border-color:\s*var\(--nfc-premium-line\) !important;/);
    assert.ok(premium.includes('.nfc-plan-detail-page .nfc-lifecycle-strip {'));
  });

  test('all current and future stylesheets are accounted for by exhaustive audit', () => {
    const audit = read('scripts/check-console-css-ownership.mjs');
    for (const name of styles) assert.ok(audit.includes("'legacy-reviewed:" + name + "'"));
    assert.ok(audit.includes("cssFiles(root)"));
    assert.ok(audit.includes("Unreviewed CSS file:"));
    assert.ok(audit.includes("Duplicate CSS ownership entry"));
    assert.ok(audit.includes("Incomplete CSS inventory coverage"));
    assert.ok(audit.includes("if (errors.length) process.exitCode = 1"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_final_pages_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_final_pages_css.test.js'));
  });
});
