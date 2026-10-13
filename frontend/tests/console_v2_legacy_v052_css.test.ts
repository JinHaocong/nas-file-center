import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed v052 final audit CSS retirement', () => {
  const css = read('src/styles/v052-final-audit.css');

  test('v052 has no orphan AntD or anticon class selectors', () => {
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 7000, 'native audit and responsive rules remain intact');
  });

  test('native page composition, focus and settings label rules remain', () => {
    for (const marker of [
      '.nfc-page-header {',
      '.nfc-page-actions .nfc-action-bar {',
      '.nfc-data-panel-heading {',
      '.nfc-table-link:focus-visible,',
      '.nfc-mobile-dock-item:focus-visible {',
      '.nfc-system-controls-page .nfc-settings-grid {',
      '.nfc-system-controls-page .nfc-settings-control-grid > label {',
    ]) assert.ok(css.includes(marker), marker);
    assert.match(css, /\.nfc-system-controls-page \.nfc-settings-control-grid > label\s*\{\s*min-width: 0;/);
  });

  test('native directory picker, mobile list and reduced-motion rules survive mixed selectors', () => {
    for (const marker of [
      '.nfc-directory-picker-modal {',
      '.nfc-directory-list-viewport {',
      '.nfc-directory-secondary-item {',
      '.nfc-directory-secondary-item:hover {',
      '.nfc-mobile-record-actions {',
      '@media (max-width: 980px)',
      '@media (max-width: 767px)',
      '@media (max-width: 420px)',
      '@media (hover: hover)',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(marker), marker);
    assert.match(css, /\.nfc-directory-secondary-item\s*\{\s*transition: background 140ms ease, border-color 140ms ease;/);
    assert.match(css, /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.nfc-task-mobile-card,\s*\.nfc-directory-secondary-item\s*\{\s*transition: none !important;/);
  });

  test('reviewed v052 preserves cascade import position and CSS guard coverage', () => {
    const main = read('src/main.tsx');
    const before = main.indexOf("import './styles/v051-product-polish.css';");
    const current = main.indexOf("import './styles/v052-final-audit.css';");
    const after = main.indexOf("import './styles/v054-premium-system.css';");
    const native = main.indexOf("import './styles/console-v2.css';");
    assert.ok(before >= 0 && before < current && current < after && after < native);
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v052-final-audit.css'"));
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
  });
});
