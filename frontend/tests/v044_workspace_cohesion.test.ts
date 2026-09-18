import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.4 workspace cohesion audit', () => {
  test('header uses workspace context instead of duplicating sidebar brand', () => {
    const header = read('src/components/Header.tsx');
    assert.match(header, /nfc-header-workspace/);
    assert.match(header, /CONTROL PLANE/);
    assert.match(header, /Local operations/);
    assert.doesNotMatch(header, /nfc-header-brand-dot/);
    assert.doesNotMatch(header, /style=\{\{/);
  });

  test('shell and right-side primitives share the same workspace surface language', () => {
    const css = read('src/index.css');
    assert.match(css, /--nfc-workspace-surface:/);
    assert.match(css, /--nfc-workspace-radius:/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*var\(--nfc-workspace-surface\)/);
    assert.match(css, /\.nfc-page-header[\s\S]*var\(--nfc-workspace-surface\)/);
    assert.match(css, /\.nfc-data-panel[\s\S]*var\(--nfc-workspace-surface\)/);
  });

  test('dashboard metrics are independent workspace tiles rather than a joined grid', () => {
    const css = read('src/index.css');
    assert.match(css, /\.nfc-metric-grid\s*\{[^}]*gap:/s);
    assert.match(css, /\.nfc-metric-card\s*\{[^}]*border:\s*1px solid/s);
    assert.match(css, /\.nfc-metric-card\s*\{[^}]*border-radius:/s);
  });

  test('page headers use one surface with actions instead of floating title chrome', () => {
    const css = read('src/index.css');
    assert.match(css, /\.nfc-page-header\s*\{[^}]*padding:/s);
    assert.match(css, /\.nfc-page-header\s*\{[^}]*border:/s);
    assert.match(css, /\.nfc-page-actions\s*\{[^}]*background:\s*transparent/s);
  });

  test('mobile workspace surfaces collapse cleanly to one-column interaction', () => {
    const css = read('src/index.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-page-header[\s\S]*flex-direction:\s*column/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-page-actions[\s\S]*width:\s*100%/s);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-metric-grid[\s\S]*grid-template-columns:\s*repeat\(2/s);
  });

  test('background, shadow and radius inherit the sidebar visual language', () => {
    const css = read('src/index.css');
    assert.match(css, /--nfc-workspace-surface:\s*var\(--nfc-nav-surface\)/);
    assert.match(css, /--nfc-workspace-hairline:\s*var\(--nfc-shell-hairline\)/);
    assert.match(css, /--nfc-workspace-radius:\s*var\(--nfc-shell-radius\)/);
    assert.match(css, /--nfc-workspace-shadow:\s*var\(--nfc-shell-shadow\)/);
    assert.match(css, /--nfc-workspace-radius-inner:\s*11px/);
    assert.match(css, /\.nfc-login-panel,[\s\S]*\.nfc-overlay-modal \.ant-modal-content[\s\S]*var\(--nfc-workspace-surface\)/s);
    assert.match(css, /\.nfc-operations-page \.ant-card,[\s\S]*box-shadow:\s*none !important/s);
  });

});
