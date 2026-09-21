import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.7 control plane foundation', () => {
  test('frontend loads the v0.4.7 style ownership root after legacy base css', () => {
    const main = read('src/main.tsx');
    assert.match(main, /import '\.\/index\.css';[\s\S]*import '\.\/styles\/v047\.css';/);
    const entry = read('src/styles/v047.css');
    for (const file of ['tokens.css', 'foundation.css', 'shell.css', 'primitives.css', 'overlays.css', 'responsive.css']) {
      assert.match(entry, new RegExp(file.replace('.', '\\.')));
    }
  });

  test('glass remains available for shell and overlays but workspace surfaces are opaque', () => {
    const css = read('src/styles/tokens.css');
    assert.match(css, /--nfc-glass-shell-bg:/);
    assert.match(css, /--nfc-overlay-surface-bg:/);
    assert.match(css, /--nfc-glass-workspace-bg: var\(--nfc-surface-1\)/);
    assert.match(css, /--nfc-blur-workspace: 0px/);
  });

  test('sidebar remains the visual anchor while header becomes an integrated command rail', () => {
    const css = read('src/styles/shell.css');
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar[\s\S]*var\(--nfc-nav-surface\)/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*border-bottom: 1px solid var\(--nfc-border-soft\)[\s\S]*border-radius: 0/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*backdrop-filter:/);
  });

  test('page header is unboxed and data panels preserve all semantic variants', () => {
    const component = read('src/components/ui/DataPanel.tsx');
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-page-header[\s\S]*background: transparent[\s\S]*box-shadow: none/);
    assert.match(component, /DataPanelVariant = 'default' \| 'dense' \| 'quiet' \| 'danger' \| 'floating'/);
    for (const variant of ['default', 'dense', 'quiet', 'danger', 'floating']) {
      assert.match(css, new RegExp('\\.nfc-data-panel-' + variant));
    }
  });

  test('metrics form one instrument strip instead of independent glass cards', () => {
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-metric-grid[\s\S]*gap: 0[\s\S]*border: 1px solid/);
    assert.match(css, /\.nfc-metric-card[\s\S]*border-radius: 0[\s\S]*background: transparent[\s\S]*box-shadow: none/);
  });

  test('dense tables use restrained headers and flat rows', () => {
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-data-panel \.ant-table-thead[\s\S]*text-transform: none/);
    assert.match(css, /\.nfc-data-panel \.ant-table-tbody[\s\S]*border-bottom-color/);
  });

  test('floating Ant surfaces retain deliberate overlay depth', () => {
    const css = read('src/styles/overlays.css');
    assert.match(css, /\.ant-modal \.ant-modal-content,[\s\S]*\.ant-select-dropdown,[\s\S]*var\(--nfc-overlay-surface-bg\)/);
    assert.match(css, /var\(--nfc-shadow-overlay\)/);
    assert.match(css, /var\(--nfc-blur-overlay\)/);
  });

  test('mobile keeps the unboxed hierarchy and a real two-column metric instrument', () => {
    const css = read('src/styles/responsive.css');
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-page-header[\s\S]*flex-direction: column/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-metric-grid[\s\S]*repeat\(2/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-header\.nfc-header[\s\S]*border-radius: 0/);
  });

  test('settings topology regression remains explicitly protected', () => {
    const settings = read('src/styles/pages/settings.css');
    assert.match(settings, /grid-template-areas:[\s\S]*"runtime lifecycle"[\s\S]*"resource lifecycle"[\s\S]*"sessions sessions"/);
  });

  test('operational table pages stay on the dense semantic surface', () => {
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

  test('all routed workspaces retain semantic roots for page-specific composition', () => {
    const pages: Array<[string, RegExp]> = [
      ['src/pages/Dashboard/index.tsx', /nfc-dashboard-page/],
      ['src/pages/Indexes/index.tsx', /nfc-indexes-page/],
      ['src/pages/Scans/index.tsx', /nfc-scans-page/],
      ['src/pages/Scans/ScanDetail.tsx', /nfc-scan-detail-page/],
      ['src/pages/Scans/AdvancedDedupePage.tsx', /nfc-advanced-dedupe-page/],
      ['src/pages/PathMatch/index.tsx', /nfc-path-match-page/],
      ['src/pages/Rename/index.tsx', /nfc-rename-page/],
      ['src/pages/Batch/index.tsx', /nfc-batch-page/],
      ['src/pages/Organizer/index.tsx', /nfc-organizer-page/],
      ['src/pages/Plans/index.tsx', /nfc-plans-page/],
      ['src/pages/Plans/PlanDetail.tsx', /nfc-plan-detail-page/],
      ['src/pages/Quarantine/index.tsx', /nfc-quarantine-page/],
      ['src/pages/Tasks/index.tsx', /nfc-tasks-page/],
      ['src/pages/Audit/index.tsx', /nfc-audit-page/],
      ['src/pages/Settings/index.tsx', /nfc-settings-page/],
      ['src/pages/Workflows/WorkflowList.tsx', /nfc-workflows-page/],
      ['src/pages/Workflows/WorkflowBuilder.tsx', /nfc-workflow-builder-page/],
      ['src/pages/Login/index.tsx', /nfc-login-shell/],
    ];
    for (const [path, root] of pages) assert.match(read(path), root, path);
  });

  test('style ownership remains split across page-specific files', () => {
    const entry = read('src/styles/v047.css');
    for (const file of [
      'pages/dashboard.css',
      'pages/operations.css',
      'pages/details.css',
      'pages/tools.css',
      'pages/organizer.css',
      'pages/workflows.css',
      'pages/settings.css',
      'pages/login.css',
    ]) {
      assert.match(entry, new RegExp(file.replace('.', '\\.')));
    }
  });

  test('page composition keeps deliberate hierarchy without conflicting legacy overrides', () => {
    const dashboard = read('src/styles/pages/dashboard.css');
    const tools = read('src/styles/pages/tools.css');
    const settings = read('src/styles/pages/settings.css');
    const workflows = read('src/styles/pages/workflows.css');
    assert.match(dashboard, /grid-template-columns: minmax\(0, 1\.82fr\) minmax\(284px, 0\.58fr\)/);
    assert.match(tools, /\.nfc-path-match-page \.nfc-tool-workbench[\s\S]*var\(--nfc-v49-radius-lg/);
    assert.doesNotMatch(tools, /border-radius: 0 !important/);
    assert.match(settings, /\.nfc-settings-subpanel:last-child[\s\S]*border-bottom: 0/);
    assert.doesNotMatch(settings, /border-top: 1px solid/);
    assert.match(workflows, /\.nfc-workflow-builder-page \.nfc-complex-form-panel[\s\S]*var\(--nfc-v49-radius-lg/);
    assert.match(workflows, /\.nfc-workflow-step-card[\s\S]*border-top: 1px solid/);
  });

  test('legacy terminal v0.4.4 override ledgers stay out of index css', () => {
    const legacy = read('src/index.css');
    assert.doesNotMatch(legacy, /v0\.4\.4 Workspace Cohesion Pass/);
    assert.doesNotMatch(legacy, /v0\.4\.4 Sidebar Visual Language Parity Lock/);
    assert.doesNotMatch(legacy, /v0\.4\.4 shared component substrate parity/);
    assert.doesNotMatch(legacy, /v0\.4\.4 Settings desktop topology follow-up/);
  });
});
