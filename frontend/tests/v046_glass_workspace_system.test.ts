import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.6 glass workspace system foundation', () => {
  test('frontend loads the split v0.4.6 style entry after legacy CSS', () => {
    const main = read('src/main.tsx');
    assert.match(main, /import '\.\/index\.css';[\s\S]*import '\.\/styles\/v046\.css';/);
    const entry = read('src/styles/v046.css');
    for (const file of ['tokens.css', 'foundation.css', 'shell.css', 'primitives.css', 'overlays.css', 'responsive.css']) {
      assert.match(entry, new RegExp(file.replace('.', '\\.')));
    }
  });

  test('glass tiers and opaque fallback are named centrally', () => {
    const css = read('src/styles/tokens.css');
    for (const token of [
      '--nfc-glass-shell-bg',
      '--nfc-glass-workspace-bg',
      '--nfc-dense-surface-bg',
      '--nfc-overlay-surface-bg',
      '--nfc-blur-shell',
      '--nfc-blur-workspace',
      '--nfc-blur-overlay',
    ]) {
      assert.match(css, new RegExp(token));
    }
    assert.match(css, /@supports not \(\(backdrop-filter: blur\(1px\)\)/);
  });

  test('shell glass is deliberate while sidebar remains an opaque identity plane', () => {
    const css = read('src/styles/shell.css');
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*var\(--nfc-glass-shell-bg\)[\s\S]*backdrop-filter:/);
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar[\s\S]*var\(--nfc-nav-surface\)/);
  });

  test('shared primitives expose workspace, dense, quiet, danger and floating panels', () => {
    const component = read('src/components/ui/DataPanel.tsx');
    const css = read('src/styles/primitives.css');
    assert.match(component, /DataPanelVariant = 'default' \| 'dense' \| 'quiet' \| 'danger' \| 'floating'/);
    for (const variant of ['default', 'dense', 'quiet', 'danger', 'floating']) {
      assert.match(css, new RegExp('\\.nfc-data-panel-' + variant));
    }
  });

  test('page header, metric cards and workbenches consume the shared workspace glass', () => {
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-page-header[\s\S]*var\(--nfc-glass-workspace-bg\)/);
    assert.match(css, /\.nfc-metric-card[\s\S]*var\(--nfc-glass-workspace-bg\)/);
    assert.match(css, /\.nfc-tool-workbench,[\s\S]*var\(--nfc-glass-workspace-bg\)/);
  });

  test('floating Ant surfaces share one overlay glass treatment', () => {
    const css = read('src/styles/overlays.css');
    assert.match(css, /\.ant-modal \.ant-modal-content,[\s\S]*\.ant-select-dropdown,[\s\S]*var\(--nfc-overlay-surface-bg\)/);
    assert.match(css, /var\(--nfc-shadow-overlay\)/);
    assert.match(css, /var\(--nfc-blur-overlay\)/);
  });

  test('mobile reduces blur and keeps workspace hierarchy responsive', () => {
    const css = read('src/styles/responsive.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*--nfc-blur-shell: 14px/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-page-header[\s\S]*padding: 16px/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-metric-grid[\s\S]*repeat\(2/);
  });

  test('settings topology regression remains explicitly protected', () => {
    const settings = read('src/styles/pages/settings.css');
    assert.match(settings, /grid-template-areas:[\s\S]*"runtime lifecycle"[\s\S]*"resource lifecycle"[\s\S]*"sessions sessions"/);
  });
  test('deep component surfaces cover directory picker, task runtime and destructive flows', () => {
    const css = read('src/styles/components.css');
    assert.match(css, /\.nfc-directory-browser-toolbar[\s\S]*var\(--nfc-dense-surface-bg\)/);
    assert.match(css, /\.nfc-worker-status-strip[\s\S]*var\(--nfc-glass-workspace-bg\)/);
    assert.match(css, /\.nfc-overlay-section[\s\S]*var\(--nfc-dense-surface-bg\)/);
    assert.match(css, /\.nfc-destructive-confirm[\s\S]*var\(--nfc-danger-soft\)/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-task-action-bar/);
  });

  test('operational table pages opt into dense data surfaces', () => {
    for (const path of [
      'src/pages/Indexes/index.tsx',
      'src/pages/Scans/index.tsx',
      'src/pages/Plans/index.tsx',
      'src/pages/Quarantine/index.tsx',
      'src/pages/Tasks/index.tsx',
      'src/pages/Audit/index.tsx',
      'src/pages/Workflows/WorkflowList.tsx',
    ]) {
      assert.match(read(path), /variant="dense"/);
    }
  });
});
