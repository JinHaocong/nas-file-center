import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.4 workspace cohesion audit (carried forward by v0.4.6)', () => {
  test('header uses workspace context instead of duplicating sidebar brand', () => {
    const header = read('src/components/Header.tsx');
    assert.match(header, /nfc-header-workspace/);
    assert.match(header, /CONTROL PLANE/);
    assert.match(header, /Local operations/);
    assert.doesNotMatch(header, /nfc-header-brand-dot/);
    assert.doesNotMatch(header, /style=\{\{/);
  });

  test('shell and right-side primitives share the current workspace token system', () => {
    const tokens = read('src/styles/tokens.css');
    const shell = read('src/styles/shell.css');
    const primitives = read('src/styles/primitives.css');
    assert.match(tokens, /--nfc-glass-shell-bg:/);
    assert.match(tokens, /--nfc-glass-workspace-bg:/);
    assert.match(tokens, /--nfc-border-soft:/);
    assert.match(shell, /\.nfc-header\.nfc-header[\s\S]*var\(--nfc-glass-shell-bg\)/);
    assert.match(primitives, /\.nfc-page-header[\s\S]*var\(--nfc-glass-workspace-bg\)/);
    assert.match(primitives, /\.nfc-data-panel-default[\s\S]*var\(--nfc-glass-workspace-bg\)/);
  });

  test('dashboard metrics are independent workspace tiles rather than a joined grid', () => {
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-metric-grid\s*\{[^}]*gap:/s);
    assert.match(css, /\.nfc-metric-card\s*\{[^}]*border:\s*1px solid/s);
    assert.match(css, /\.nfc-metric-card\s*\{[^}]*border-radius:/s);
  });

  test('page headers remain a single workspace surface with grouped actions', () => {
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-page-header\s*\{[^}]*padding:/s);
    assert.match(css, /\.nfc-page-header\s*\{[^}]*border:/s);
    assert.match(css, /\.nfc-page-actions\s*\{[^}]*background:/s);
  });

  test('mobile workspace surfaces collapse cleanly to one-column interaction', () => {
    const css = read('src/styles/responsive.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-page-header[\s\S]*padding:\s*16px/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-page-actions[\s\S]*width:\s*100%/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-metric-grid[\s\S]*grid-template-columns:\s*repeat\(2/s);
  });

  test('surface depth is driven by named shared tokens rather than page-local shadow systems', () => {
    const tokens = read('src/styles/tokens.css');
    assert.match(tokens, /--nfc-shadow-shell:/);
    assert.match(tokens, /--nfc-shadow-workspace:/);
    assert.match(tokens, /--nfc-radius-shell:/);
    assert.match(tokens, /--nfc-radius-workspace:/);
    assert.match(tokens, /--nfc-radius-inner:/);
  });

  test('shared dropdowns and Ant component substrates use the overlay surface system', () => {
    const css = read('src/styles/overlays.css');
    assert.match(css, /\.ant-dropdown \.ant-dropdown-menu,[\s\S]*var\(--nfc-overlay-surface-bg\)/s);
    assert.match(css, /\.ant-select-dropdown,[\s\S]*var\(--nfc-shadow-overlay\)/s);
    assert.match(css, /\.ant-modal \.ant-modal-content,[\s\S]*var\(--nfc-overlay-surface-bg\)/s);
  });

  test('settings keeps explicit desktop areas so tall lifecycle content cannot create a blank left row', () => {
    const page = read('src/pages/Settings/index.tsx');
    const css = read('src/styles/pages/settings.css');

    assert.match(page, /nfc-settings-panel-runtime/);
    assert.match(page, /nfc-settings-panel-lifecycle/);
    assert.match(page, /nfc-settings-panel-resource/);
    assert.match(page, /nfc-settings-panel-sessions/);
    assert.match(css, /grid-template-areas:[\s\S]*"runtime lifecycle"[\s\S]*"resource lifecycle"[\s\S]*"sessions sessions"/s);
    assert.match(css, /@media \(max-width: 1199px\)[\s\S]*"runtime"[\s\S]*"lifecycle"[\s\S]*"resource"[\s\S]*"sessions"/s);
  });
});
