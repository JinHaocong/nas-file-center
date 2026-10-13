import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed v054 premium system CSS retirement', () => {
  const css = read('src/styles/v054-premium-system.css');

  test('v054 has zero leftover AntD or anticon class selectors', () => {
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 30000, 'retain reviewed native workspace styles');
  });

  test('mixed groups retain native status and keyboard focus behavior', () => {
    assert.match(css, /\.nfc-header-status-badge\s*\{[^}]*min-height:\s*24px;/);
    assert.match(css, /\.nfc-app-main \.nfc-row-actions:focus-within\s*\{\s*opacity:\s*1;/);
    assert.match(css, /\.nfc-app-main \.nfc-form-note,\s*\.nfc-app-main \.nfc-step-editor-note\s*\{[^}]*color:\s*var\(--nfc-text-subtle\);/);
  });

  test('native panel effects, row controls and overlay geometry remain', () => {
    for (const marker of [
      '.nfc-app-main .nfc-data-panel-default,',
      '.nfc-app-main .nfc-metric-card::before,',
      '.nfc-app-main .nfc-row-actions {',
      '.nfc-overlay-section-flush > .nfc-responsive-data-view {',
      '.nfc-app-main .nfc-page-header {',
      '.nfc-app-main .nfc-page-actions {',
      '.nfc-app-main .nfc-workflow-mode-grid {',
    ]) assert.ok(css.includes(marker), marker);
    assert.match(css, /\.nfc-overlay-section-flush > \.nfc-responsive-data-view\s*\{\s*border-radius:\s*0 0 12px 12px;/);
  });

  test('responsive, reduced motion and reduced transparency retain native rules', () => {
    for (const marker of [
      '@media (max-width: 1199px)',
      '@media (max-width: 980px)',
      '@media (max-width: 767px)',
      '@media (max-width: 420px)',
      '@media (hover: hover)',
      '@media (prefers-reduced-motion: reduce)',
      '@media (prefers-reduced-transparency: reduce)',
    ]) assert.ok(css.includes(marker), marker);
    assert.match(css, /@media \(prefers-reduced-transparency: reduce\)\s*\{\s*\.nfc-header\.nfc-header\s*\{[^}]*backdrop-filter:\s*none !important;/);
    assert.match(css, /\.nfc-app-main \.nfc-data-panel-default,\s*\.nfc-app-main \.nfc-metric-card::before,\s*\.nfc-app-main \.nfc-row-actions\s*\{\s*transition:\s*none !important;/);
  });

  test('imports remain ordered and 54-sheet ownership audit invokes this regression', () => {
    const main = read('src/main.tsx');
    const prev = main.indexOf("import './styles/v052-final-audit.css';");
    const curr = main.indexOf("import './styles/v054-premium-system.css';");
    const next = main.indexOf("import './styles/v055-workspace-breathing.css';");
    const native = main.indexOf("import './styles/console-v2.css';");
    assert.ok(prev >= 0 && prev < curr && curr < next && next < native);
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v054-premium-system.css'"));
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_v054_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_v054_css.test.js'));
  });
});
