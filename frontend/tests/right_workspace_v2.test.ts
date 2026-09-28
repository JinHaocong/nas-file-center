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
    assert.match(css, /\.nfc-page-title[\s\S]*font-size:\s*clamp\(30px/);
    assert.match(css, /\.nfc-data-panel-body[\s\S]*border-radius:\s*var\(--nfc-w2-radius-md\)/);
    assert.match(css, /\.nfc-data-panel \.ant-table-tbody > tr > td[\s\S]*font-size:\s*12\.75px/);
    assert.match(css, /\.nfc-dashboard-page/);
    assert.match(css, /\.nfc-quarantine-page/);
    assert.match(css, /\.nfc-workflow-builder-page/);
    assert.match(css, /\.nfc-settings-page/);
    assert.match(css, /\.nfc-advanced-dedupe-page/);
  });

  test('workspace width modes prevent workbench forms from collapsing into a left-aligned reading column', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');
    const pathMatch = read('src/pages/PathMatch/index.tsx');

    assert.match(css, /--nfc-w2-workspace-max:\s*2100px/);
    assert.match(css, /\.nfc-page-content > \.nfc-page-layout-workbench/);
    assert.match(css, /\.nfc-operations-page\.nfc-page-layout-workbench[\s\S]*max-width:\s*var\(--nfc-w2-workspace-max\)/);
    assert.match(
      css,
      /\.nfc-page-layout-workbench \.nfc-file-tool-form[\s\S]*max-width:\s*none/
    );
    assert.match(pathMatch, /nfc-path-match-page nfc-page-layout-workbench/);
    assert.match(pathMatch, /className="nfc-path-match-form"/);
    assert.doesNotMatch(pathMatch, /eyebrow="Path matching"/);
  });

  test('data ledgers opt into the wide workspace mode', () => {
    const ledgerFiles = [
      'src/pages/Indexes/index.tsx',
      'src/pages/Media/index.tsx',
      'src/pages/Scans/index.tsx',
      'src/pages/Plans/index.tsx',
      'src/pages/Quarantine/index.tsx',
      'src/pages/Tasks/index.tsx',
      'src/pages/Audit/index.tsx',
      'src/pages/Workflows/WorkflowList.tsx',
    ];

    for (const path of ledgerFiles) {
      assert.match(read(path), /nfc-page-layout-ledger/);
    }

    const css = read('src/styles/v056-right-workspace-v2.css');
    assert.match(css, /\.nfc-page-layout-ledger \.nfc-filter-bar[\s\S]*flex-wrap:\s*wrap/);
    assert.match(css, /\.nfc-page-layout-ledger \.nfc-search-input[\s\S]*max-width:\s*560px/);
  });

  test('file tools and organizer use the workbench width contract', () => {
    const workbenchFiles = [
      'src/pages/PathMatch/index.tsx',
      'src/pages/Rename/index.tsx',
      'src/pages/Batch/index.tsx',
      'src/pages/Organizer/index.tsx',
      'src/pages/Organizer/ProfilePreview.tsx',
    ];

    for (const path of workbenchFiles) {
      assert.match(read(path), /nfc-page-layout-workbench/);
    }

    assert.doesNotMatch(read('src/pages/Rename/index.tsx'), /eyebrow="Rename workspace"/);
    assert.doesNotMatch(read('src/pages/Batch/index.tsx'), /eyebrow="Batch operations"/);
    assert.doesNotMatch(read('src/pages/Organizer/index.tsx'), /eyebrow="Organizer profiles"/);

    const css = read('src/styles/v056-right-workspace-v2.css');
    assert.match(css, /\.nfc-page-layout-workbench \.nfc-form-grid[\s\S]*repeat\(2/);
    assert.match(css, /\.nfc-batch-page \.nfc-batch-operation-grid[\s\S]*repeat\(3/);
  });

  test('complex editors and detail pages use dedicated width contracts', () => {
    const advanced = read('src/pages/Scans/AdvancedDedupePage.tsx');
    const builder = read('src/pages/Workflows/WorkflowBuilder.tsx');
    const scanDetail = read('src/pages/Scans/ScanDetail.tsx');
    const planDetail = read('src/pages/Plans/PlanDetail.tsx');
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(advanced, /nfc-page-layout-workbench/);
    assert.match(builder, /nfc-page-layout-workbench/);
    assert.match(scanDetail, /nfc-page-layout-detail/);
    assert.match(planDetail, /nfc-page-layout-detail/);
    assert.doesNotMatch(advanced, /eyebrow="ADVANCED DEDUPE"/);
    assert.doesNotMatch(builder, /eyebrow="WORKFLOW BUILDER"/);
    assert.doesNotMatch(scanDetail, /eyebrow="SCAN SNAPSHOT"/);
    assert.doesNotMatch(planDetail, /eyebrow="EXECUTION PLAN"/);

    assert.match(css, /--nfc-w2-detail-max:\s*1880px/);
    assert.match(css, /grid-template-columns:\s*minmax\(300px, 340px\) minmax\(0, 1fr\)/);
    assert.match(css, /grid-template-columns:\s*minmax\(320px, 360px\) minmax\(0, 1fr\)/);
  });

  test('dashboard settings login and overlays have dedicated composition rules', () => {
    const dashboard = read('src/pages/Dashboard/index.tsx');
    const settings = read('src/pages/Settings/index.tsx');
    const loginCss = read('src/styles/pages/login.css');
    const settingsCss = read('src/styles/pages/settings.css');
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(dashboard, /nfc-page-layout-dashboard/);
    assert.match(settings, /nfc-page-layout-workbench/);
    assert.doesNotMatch(dashboard, /eyebrow="Operations overview"/);
    assert.doesNotMatch(settings, /eyebrow="System controls"/);

    assert.match(css, /--nfc-w2-dashboard-max:\s*1800px/);
    assert.match(css, /minmax\(300px, 340px\)/);
    assert.match(css, /\.ant-modal-footer[\s\S]*border-top:/);
    assert.match(settingsCss, /grid-template-columns:\s*repeat\(12/);
    assert.match(loginCss, /width:\s*min\(432px, 100%\)/);
    assert.match(loginCss, /\.nfc-login-security-note[\s\S]*border:\s*1px solid/);
  });

  test('responsive cascade keeps semantic page widths authoritative', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /--nfc-w2-page-bottom:\s*clamp\(96px, 8vh, 128px\)/);
    assert.match(css, /padding:\s*30px clamp\(24px, 2\.15vw, 42px\) var\(--nfc-w2-page-bottom\)/);
    assert.doesNotMatch(
      css,
      /\.nfc-app-main \.nfc-page-content > \.nfc-quarantine-page,/
    );
    assert.match(
      css,
      /@media \(max-width: 1199px\)[\s\S]*\.nfc-app-main \.nfc-page-header[\s\S]*flex-wrap:\s*wrap/
    );
    assert.match(
      css,
      /\.nfc-page-layout-ledger \.nfc-search-input[\s\S]*flex-basis:\s*100%/
    );

    const main = read('src/main.tsx');
    assert.doesNotMatch(main, /v057|v058/);
  });

  test('global visual rhythm keeps section titles clear and restores intentional padding', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');
    const toolsCss = read('src/styles/pages/tools.css');

    assert.match(css, /--nfc-w2-panel-pad-x:\s*clamp\(18px, 1\.2vw, 24px\)/);
    assert.match(css, /\.nfc-data-panel-header[\s\S]*margin:\s*0;[\s\S]*padding:\s*0 4px 14px/);
    assert.match(css, /\.nfc-data-panel-title[\s\S]*line-height:\s*1\.4/);
    assert.match(
      css,
      /\.nfc-data-panel:not\(\.nfc-panel-flush\):not\(\.nfc-tool-workbench\)[\s\S]*padding:\s*var\(--nfc-w2-panel-pad-y\) var\(--nfc-w2-panel-pad-x\)/
    );
    assert.match(css, /\.nfc-rename-page \.nfc-data-panel-body,[\s\S]*padding:\s*26px 28px/);
    assert.doesNotMatch(toolsCss, /margin:\s*-20px -22px 18px/);
    assert.doesNotMatch(toolsCss, /margin:\s*-16px -12px 15px/);
    assert.match(toolsCss, /\.nfc-rename-page \.nfc-tool-workbench > \.nfc-data-panel-header[\s\S]*margin:\s*0 0 14px/);
  });

  test('glass treatment is constrained to utility and overlay surfaces', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*backdrop-filter:\s*blur\(22px\)/);
    assert.match(css, /\.ant-modal-content,[\s\S]*\.ant-drawer-content[\s\S]*backdrop-filter:\s*blur\(24px\)/);
    assert.match(css, /\.nfc-quarantine-page \.nfc-bulk-action-bar[\s\S]*backdrop-filter:\s*blur\(18px\)/);
    assert.doesNotMatch(css, /\.nfc-data-panel-body[^{]*\{[^}]*backdrop-filter/);
  });
});
