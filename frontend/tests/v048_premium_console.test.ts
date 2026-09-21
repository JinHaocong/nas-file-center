import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.8 premium console visual system', () => {
  test('v0.4.8 is loaded after v0.4.7 so the right workspace owns final presentation', () => {
    const main = read('src/main.tsx');
    assert.match(
      main,
      /import '\.\/styles\/v047\.css';[\s\S]*import '\.\/styles\/v048\.css';/
    );
  });

  test('approved sidebar visual language is deliberately not overridden', () => {
    const css = read('src/styles/v048.css');
    assert.doesNotMatch(css, /\.nfc-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-sidebar-menu(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-brand(?:\b|\.)/);
  });

  test('header is an integrated command rail rather than a floating card', () => {
    const css = read('src/styles/v048.css');
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*border-bottom: 1px solid var\(--nfc-premium-line\)/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*border-radius: 0/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*box-shadow: none/);
  });

  test('page hierarchy is driven by typography and spacing before containers', () => {
    const css = read('src/styles/v048.css');
    assert.match(css, /\.nfc-page-content[\s\S]*padding: 34px 34px 52px/);
    assert.match(css, /\.nfc-page-header[\s\S]*border-bottom: 1px solid var\(--nfc-premium-line\)/);
    assert.match(css, /\.nfc-page-title[\s\S]*clamp\(28px, 2\.45vw, 38px\)/);
  });

  test('metrics remain one instrument strip and do not regress to card deck chrome', () => {
    const css = read('src/styles/v048.css');
    assert.match(css, /\.nfc-metric-grid[\s\S]*gap: 0[\s\S]*border-radius: var\(--nfc-premium-radius-lg\)/);
    assert.match(css, /\.nfc-metric-card[\s\S]*border-radius: 0[\s\S]*box-shadow: none/);
  });

  test('dense tables and forms share one restrained control language', () => {
    const css = read('src/styles/v048.css');
    assert.match(css, /\.nfc-data-panel \.ant-table-thead/);
    assert.match(css, /\.nfc-data-panel \.ant-table-tbody/);
    assert.match(css, /\.nfc-app-shell \.ant-input/);
    assert.match(css, /\.nfc-app-shell \.ant-select-selector/);
    assert.match(css, /--nfc-premium-control: 38px/);
  });

  test('settings, overlays and mobile records are covered by the same system', () => {
    const css = read('src/styles/v048.css');
    assert.match(css, /\.nfc-settings-subpanel-header/);
    assert.match(css, /\.ant-modal-content/);
    assert.match(css, /\.nfc-task-mobile-card/);
    assert.match(css, /@media \(max-width: 767px\)/);
  });

  test('dark mode has dedicated premium tokens rather than relying on light fallbacks', () => {
    const css = read('src/styles/v048.css');
    assert.match(css, /\[data-theme='dark'\][\s\S]*--nfc-premium-canvas:/);
    assert.match(css, /\[data-theme='dark'\][\s\S]*--nfc-premium-surface:/);
    assert.match(css, /\[data-theme='dark'\][\s\S]*--nfc-premium-line:/);
  });
});


describe('v0.4.8 page composition pass', () => {
  test('page composition layer loads after the global premium console layer', () => {
    const main = read('src/main.tsx');
    assert.match(
      main,
      /import '\.\/styles\/v048\.css';[\s\S]*import '\.\/styles\/v048-pages\.css';/
    );
  });

  test('page composition layer keeps the approved navigation untouched', () => {
    const css = read('src/styles/v048-pages.css');
    assert.doesNotMatch(css, /\.nfc-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-sidebar-menu(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-brand(?:\b|\.)/);
  });

  test('dashboard uses a contextual rail instead of stacked right-side cards', () => {
    const css = read('src/styles/v048-pages.css');
    assert.match(css, /\.nfc-dashboard-page \.nfc-dashboard-rail[\s\S]*border-left: 1px solid var\(--nfc-premium-line\)/);
    assert.match(css, /\.nfc-dashboard-page \.nfc-dashboard-rail > \.nfc-data-panel[\s\S]*border: 0 !important[\s\S]*background: transparent !important/);
  });

  test('dense operational pages are continuous ledgers', () => {
    const css = read('src/styles/v048-pages.css');
    assert.match(css, /\.nfc-indexes-page > \.nfc-data-panel-dense/);
    assert.match(css, /\.nfc-quarantine-page > \.nfc-data-panel-dense/);
    assert.match(css, /border-radius: 0 !important/);
  });

  test('workflow steps become one editing flow instead of card stack chrome', () => {
    const css = read('src/styles/v048-pages.css');
    assert.match(css, /\.nfc-workflow-builder-page \.nfc-workflow-step-card[\s\S]*border-bottom: 1px solid var\(--nfc-premium-line\)/);
    assert.match(css, /\.nfc-workflow-builder-page \.nfc-workflow-step-card\.is-expanded[\s\S]*border-left: 2px solid/);
  });

  test('settings top-level panels are editorial columns while danger stays explicit', () => {
    const css = read('src/styles/v048-pages.css');
    assert.match(css, /\.nfc-system-controls-page \.nfc-settings-grid > \.nfc-data-panel[\s\S]*border: 0 !important/);
    assert.match(css, /\.nfc-system-controls-page \.nfc-settings-subpanel-danger[\s\S]*border: 1px solid/);
  });
});
