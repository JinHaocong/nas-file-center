import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed v049 legacy workspace CSS retirement', () => {
  const css = read('src/styles/v049-workspace.css');

  test('v049 has no remaining AntD or anticon class selectors', () => {
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 35000, 'preserve substantial native workspace rules');
  });

  test('native row action keyboard visibility and mobile pagination survive mixed groups', () => {
    assert.match(css, /\.nfc-row-actions\s*\{[^}]*opacity:\s*0\.72;/);
    assert.match(css, /\.nfc-row-actions:focus-within\s*\{[^}]*opacity:\s*1;/);
    assert.match(css, /\.nfc-mobile-pagination\s*\{[^}]*min-height:\s*50px;/);
    assert.match(css, /\.nfc-mobile-pagination\s*\{[^}]*var\(--nfc-v49-surface-soft\)/);
    assert.match(css, /\.nfc-mobile-pagination\s*\{[^}]*color-mix\(in srgb, var\(--nfc-nav-surface\) 68%, transparent\)/);
  });

  test('native dashboard, data panels, directory picker, login and settings remain', () => {
    for (const marker of [
      '.nfc-page-content {',
      '.nfc-page-actions .nfc-action-bar {',
      '.nfc-data-panel-dense {',
      '.nfc-metric-grid {',
      '.nfc-dashboard-page .nfc-dashboard-layout {',
      '.nfc-directory-list-viewport {',
      '.nfc-login-panel {',
      '.nfc-system-controls-page .nfc-settings-grid {',
      '.nfc-system-controls-page .nfc-settings-subpanel-danger {',
    ]) assert.ok(css.includes(marker), marker);
  });

  test('responsive, reduced motion and reduced transparency retain native behavior', () => {
    for (const marker of [
      '@media (min-width: 1600px)',
      '@media (max-width: 1199px)',
      '@media (max-width: 767px)',
      '@media (max-width: 420px)',
      '@media (hover: none)',
      '@media (prefers-reduced-motion: reduce)',
      '@media (prefers-reduced-transparency: reduce)',
    ]) assert.ok(css.includes(marker), marker);
    assert.match(css, /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.nfc-app-shell \*,[^}]*transition-duration:\s*0\.01ms !important;/);
    assert.match(css, /@media \(prefers-reduced-transparency: reduce\)\s*\{\s*\.nfc-header\.nfc-header,\s*\.nfc-page-header\s*\{[^}]*background:\s*var\(--nfc-surface-1\) !important;[^}]*backdrop-filter:\s*none;/);
  });

  test('v049 retains cascade import position and becomes owned CSS', () => {
    const main = read('src/main.tsx');
    const prev = main.indexOf("import './styles/v048-detail.css';");
    const index = main.indexOf("import './styles/v049-workspace.css';");
    const next = main.indexOf("import './styles/v050-layout.css';");
    const native = main.indexOf("import './styles/console-v2.css';");
    assert.ok(prev >= 0 && prev < index && index < next && next < native);
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v049-workspace.css'"));
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_v049_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_v049_css.test.js'));
  });
});
