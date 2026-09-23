import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Right Workspace v2 design system', () => {
  test('v2 stylesheet is loaded last so it owns the right workspace cascade', () => {
    const main = read('src/main.tsx');
    const v055 = main.indexOf("import './styles/v055-workspace-breathing.css';");
    const v056 = main.indexOf("import './styles/v056-right-workspace-v2.css';");

    assert.ok(v055 >= 0);
    assert.ok(v056 > v055);
  });

  test('v2 intentionally leaves the approved sidebar and mobile navigation untouched', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.doesNotMatch(css, /\.nfc-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-sidebar-menu(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-brand(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-mobile-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-mobile-dock(?:\b|\.)/);
  });

  test('utility header no longer duplicates page identity', () => {
    const header = read('src/components/Header.tsx');

    assert.doesNotMatch(header, /WorkspaceContext/);
    assert.doesNotMatch(header, /resolveWorkspaceContext/);
    assert.doesNotMatch(header, /nfc-header-workspace/);
    assert.match(header, /SafeModeBadge/);
    assert.match(header, /WorkerStatusBadge/);
  });

  test('calm workbench hierarchy covers shared and page-specific right-side surfaces', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /--nfc-w2-control: 38px/);
    assert.match(css, /\.nfc-page-eyebrow\s*\{[\s\S]*display:\s*none/);
    assert.match(css, /\.nfc-page-title[\s\S]*font-size:\s*clamp\(28px/);
    assert.match(css, /\.nfc-data-panel-body[\s\S]*border-radius:\s*var\(--nfc-w2-radius-md\)/);
    assert.match(css, /\.nfc-data-panel \.ant-table-tbody > tr > td[\s\S]*font-size:\s*12\.75px/);
    assert.match(css, /\.nfc-dashboard-page/);
    assert.match(css, /\.nfc-quarantine-page/);
    assert.match(css, /\.nfc-workflow-builder-page/);
    assert.match(css, /\.nfc-settings-page/);
    assert.match(css, /\.nfc-advanced-dedupe-page/);
  });

  test('glass treatment is constrained to utility and overlay surfaces', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*backdrop-filter:\s*blur\(22px\)/);
    assert.match(css, /\.ant-modal-content,[\s\S]*\.ant-drawer-content[\s\S]*backdrop-filter:\s*blur\(24px\)/);
    assert.match(css, /\.nfc-quarantine-page \.nfc-bulk-action-bar[\s\S]*backdrop-filter:\s*blur\(18px\)/);
    assert.doesNotMatch(css, /\.nfc-data-panel-body[^{]*\{[^}]*backdrop-filter/);
  });
});
