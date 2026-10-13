import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 reviewed historical index.css retirement', () => {
  const css = read('src/index.css');

  test('index.css has no unreachable AntD class selectors and retains native styles', () => {
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.length > 110000, 'preserve the native source cascade');
  });

  test('native selectors survive all previously mixed AntD declarations', () => {
    for (const name of [
      '.nfc-quarantine-filter-bar .nfc-search-input {',
      '.nfc-brand {',
      '.nfc-data-panel:hover,',
      '.nfc-metric-card:hover',
      '.nfc-task-mobile-card,',
      '.nfc-mobile-activity-card',
      '.nfc-metric-value,',
      '.nfc-overlay-section-header-actions > .nfc-rebuild-name-input {',
      '.nfc-plan-detail-page .nfc-plan-action-surface .nfc-action-bar {',
      '.nfc-step-editor-note {',
      '.nfc-index-create-modal .nfc-form-note {',
    ]) assert.ok(css.includes(name), name);
    assert.match(css, /\.nfc-quarantine-filter-bar \.nfc-search-input\s*\{\s*width:\s*100%;/);
    assert.match(css, /\.nfc-index-create-modal \.nfc-form-note\s*\{[^}]*color:\s*var\(--nfc-text-subtle\);/);
  });

  test('native theme tokens, animation, responsive and reduced motion remain', () => {
    for (const marker of [
      ':root {', "[data-theme='dark']", '--nfc-accent:',
      '--nfc-shadow-sm', '--nfc-motion-enter',
      '@keyframes nfc-enter', '@keyframes nfc-status-pulse',
      '@media (max-width: 767px)', '@media (max-width: 1023px)',
      '@media (prefers-reduced-motion: reduce)',
      '.nfc-login-submit {', '.nfc-directory-picker-path-row {',
    ]) assert.ok(css.includes(marker), marker);
    assert.match(css, /\.nfc-touch-button\s*\{[^}]*min-width:\s*44px;[^}]*min-height:\s*44px;/);
    assert.match(css, /\.nfc-directory-picker-path-row\s*\{[^}]*min-height:\s*44px;/);
  });

  test('native keyboard and dialog focus remain in later component-owned CSS', () => {
    const shell = read('src/styles/console-v2.css');
    const sheet = read('src/styles/console-v2-task-overlays.css');
    assert.match(shell, /\.nfc-v2-shell button:focus-visible/);
    assert.match(shell, /\.nfc-v2-dialog-form input:focus-visible/);
    assert.match(sheet, /\.nfc-v2-sheet\.nfc-overlay-drawer/);
    assert.match(sheet, /@media \(max-width: 767px\)[\s\S]*\.nfc-v2-sheet\.nfc-overlay-drawer\s*\{\s*width:\s*100vw;/);
  });

  test('older visual regressions now verify real native controls rather than AntD DOM', () => {
    for (const path of [
      'tests/v041_premium_visual.test.ts',
      'tests/v042_console_quality.test.ts',
      'tests/v040_c6b_overlays.test.ts',
      'tests/v044_deep_ui_detail.test.ts',
    ]) {
      const source = read(path);
      assert.doesNotMatch(source, /\\\.ant-[a-z]/, path);
    }
  });

  test('index import order and 56-file audit path are authoritative', () => {
    const entry = read('src/main.tsx');
    assert.ok(entry.indexOf("import './index.css';") <
      entry.indexOf("import './styles/v047.css';"));
    assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
      entry.indexOf("import './styles/console-v2.css';"));
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-index:index.css'"));
    assert.ok(guard.includes("name.startsWith('legacy-index:') ? '..' : '.'"));
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_legacy_index_css.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_legacy_index_css.test.js'));
  });
});
