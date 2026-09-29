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
    assert.match(css, /\.nfc-page-title[\s\S]*font-size:\s*clamp\(27px/);
    assert.match(css, /\.nfc-data-panel-body[\s\S]*border-radius:\s*var\(--nfc-w2-radius-md\)/);
    assert.match(css, /\.nfc-metric-grid[\s\S]*grid-template-columns:\s*repeat\(4/);
    assert.match(css, /\.nfc-metric-grid > \.nfc-metric-card[\s\S]*grid-column:\s*auto !important/);
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
    assert.match(css, /padding:\s*18px clamp\(24px, 2\.15vw, 42px\) var\(--nfc-w2-page-bottom\)/);
    assert.doesNotMatch(
      css,
      /\.nfc-app-main \.nfc-page-content > \.nfc-quarantine-page,/
    );
    assert.match(
      css,
      /@media \(max-width: 1199px\)[\s\S]*\.nfc-app-main \.nfc-page-header[\s\S]*flex-wrap:\s*wrap/
    );
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-page-title[\s\S]*font-size:\s*24px/);
    assert.match(css, /@media \(max-width: 420px\)[\s\S]*\.nfc-app-main \.nfc-page-title[\s\S]*font-size:\s*22px/);
    assert.match(
      css,
      /\.nfc-page-layout-ledger \.nfc-search-input[\s\S]*flex-basis:\s*100%/
    );

    const main = read('src/main.tsx');
    assert.doesNotMatch(main, /v057|v058/);
  });

  test('desktop utility rail aligns with the approved sidebar shell while mobile stays edge-to-edge', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(
      css,
      /\.nfc-header\.nfc-header\s*\{[^}]*top:\s*12px;[^}]*min-height:\s*68px;[^}]*margin:\s*12px 12px 0;[^}]*border:\s*1px solid var\(--nfc-border-soft\);[^}]*border-radius:\s*var\(--nfc-radius-shell\);[^}]*background:\s*var\(--nfc-nav-surface\);/s
    );
    assert.match(
      css,
      /\.nfc-header\.nfc-header\s*\{[^}]*box-shadow:\s*0 10px 34px color-mix\(in srgb, var\(--nfc-text\) 7%, transparent\);/s
    );
    assert.match(
      css,
      /\.nfc-app-main \.nfc-page-content\s*\{[^}]*padding:\s*18px clamp\(24px, 2\.15vw, 42px\) var\(--nfc-w2-page-bottom\);/s
    );
    assert.match(
      css,
      /@media \(max-width: 767px\)[\s\S]*\.nfc-header\.nfc-header\s*\{[^}]*top:\s*0;[^}]*margin:\s*0;[^}]*border-radius:\s*0;/s
    );
  });

  test('global visual rhythm keeps section titles clear and restores intentional padding', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');
    const toolsCss = read('src/styles/pages/tools.css');
    const workspaceV49 = read('src/styles/v049-workspace.css');

    assert.match(css, /--nfc-w2-panel-pad-x:\s*clamp\(18px, 1\.2vw, 24px\)/);
    assert.match(css, /--nfc-w2-panel-header-x:\s*18px/);
    assert.match(css, /--nfc-w2-panel-header-top:\s*15px/);
    assert.match(css, /\.nfc-data-panel-header[\s\S]*margin:\s*0;[\s\S]*padding:\s*var\(--nfc-w2-panel-header-top\) var\(--nfc-w2-panel-header-x\) var\(--nfc-w2-panel-header-bottom\)/);
    assert.match(css, /\.nfc-data-panel-title[\s\S]*line-height:\s*1\.4/);
    assert.match(
      css,
      /\.nfc-data-panel:not\(\.nfc-panel-flush\):not\(\.nfc-tool-workbench\)[\s\S]*padding:\s*var\(--nfc-w2-panel-pad-y\) var\(--nfc-w2-panel-pad-x\)/
    );
    assert.match(css, /\.nfc-rename-page \.nfc-data-panel-body,[\s\S]*padding:\s*24px 26px/);
    assert.doesNotMatch(toolsCss, /margin:\s*-20px -22px 18px/);
    assert.doesNotMatch(toolsCss, /margin:\s*-16px -12px 15px/);
    assert.doesNotMatch(workspaceV49, /margin:\s*-20px -22px 18px/);
    assert.doesNotMatch(workspaceV49, /margin:\s*-16px -12px 15px/);
    assert.match(css, /\.nfc-system-controls-page \.nfc-settings-grid > \.nfc-data-panel > \.nfc-data-panel-header[\s\S]*min-height:\s*0/);
    assert.match(toolsCss, /\.nfc-rename-page \.nfc-tool-workbench > \.nfc-data-panel-header[\s\S]*margin:\s*0;[\s\S]*padding:\s*0 4px 14px/);
  });

  test('media filter command grid keeps search and destructive actions proportionate', () => {
    const media = read('src/pages/Media/index.tsx');
    const layout = read('src/styles/v050-layout.css');
    const operations = read('src/styles/pages/operations.css');

    assert.doesNotMatch(media, /style=\{\{ marginLeft: 'auto' \}\}/);
    assert.match(media, /nfc-media-destructive-action/);
    assert.match(layout, /\.nfc-media-page \.nfc-filter-bar[\s\S]*minmax\(240px, 1fr\)[\s\S]*auto[\s\S]*auto/);
    assert.match(layout, /@media \(max-width: 1499px\)[\s\S]*\.nfc-media-destructive-action[\s\S]*grid-column:\s*1 \/ -1/);
    assert.match(layout, /\.nfc-media-page \.nfc-filter-bar[\s\S]*padding:\s*14px 16px/);
    assert.match(operations, /\.nfc-tasks-page \.nfc-filter-bar[\s\S]*min-height:\s*60px[\s\S]*padding:\s*11px 14px/);
  });

  test('per-page micro polish explicitly covers every routed frontend workspace', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');
    const organizer = read('src/pages/Organizer/index.tsx');
    const profileList = read('src/pages/Organizer/ProfileList.tsx');

    for (const selector of [
      'nfc-dashboard-page',
      'nfc-indexes-page',
      'nfc-media-page',
      'nfc-scans-page',
      'nfc-scan-detail-page',
      'nfc-advanced-dedupe-page',
      'nfc-path-match-page',
      'nfc-rename-page',
      'nfc-batch-page',
      'nfc-organizer-page',
      'nfc-organizer-preview-page',
      'nfc-workflows-page',
      'nfc-workflow-builder-page',
      'nfc-plans-page',
      'nfc-plan-detail-page',
      'nfc-quarantine-page',
      'nfc-tasks-page',
      'nfc-audit-page',
      'nfc-system-controls-page',
      'nfc-login-shell',
    ]) {
      assert.match(css, new RegExp('\\.' + selector));
    }

    assert.match(css, /\.nfc-operations-page > \.nfc-page-header[\s\S]*margin-bottom:\s*0 !important/);
    assert.match(css, /\.nfc-page-layout-ledger \.ant-table-tbody > tr\.ant-table-placeholder > td[\s\S]*height:\s*220px/);
    assert.match(organizer, /title="目录整理方案"/);
    assert.match(profileList, /title="整理方案"/);
    assert.doesNotMatch(organizer, /Organizer 整理方案/);
  });

  test('ledger and workbench panel headings share one inset and no legacy accent strip', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /--nfc-w2-panel-header-x:\s*18px/);
    assert.match(
      css,
      /\.nfc-page-layout-ledger > \.nfc-data-panel > \.nfc-data-panel-header[\s\S]*padding:\s*var\(--nfc-w2-panel-header-top\) var\(--nfc-w2-panel-header-x\) var\(--nfc-w2-panel-header-bottom\)/
    );
    assert.match(
      css,
      /\.nfc-path-match-page \.nfc-tool-workbench > \.nfc-data-panel-header[\s\S]*padding:\s*var\(--nfc-w2-panel-header-top\) var\(--nfc-w2-panel-header-x\) var\(--nfc-w2-panel-header-bottom\)[\s\S]*background:\s*transparent !important/
    );
    assert.match(css, /\.nfc-tool-workbench::after[\s\S]*content:\s*none !important/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-data-panel-header[\s\S]*padding:\s*13px 14px 11px/);
  });

  test('global title system is visually calm and gives section headers real top inset', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /\.nfc-app-main \.nfc-page-title[\s\S]*font-size:\s*clamp\(27px[\s\S]*font-weight:\s*620[\s\S]*line-height:\s*1\.18/);
    assert.match(css, /\.nfc-app-main \.nfc-data-panel-title[\s\S]*font-size:\s*14px[\s\S]*font-weight:\s*620/);
    const loginCss = read('src/styles/pages/login.css');
    assert.match(loginCss, /\.nfc-login-brand h1[\s\S]*font-size:\s*21px[\s\S]*font-weight:\s*620/);
    assert.match(css, /\.nfc-dashboard-page \.nfc-dashboard-rail \.nfc-data-panel-title[\s\S]*font-size:\s*12\.5px[\s\S]*font-weight:\s*620/);
    assert.match(css, /\.nfc-app-main \.nfc-data-panel-title::before[\s\S]*content:\s*none !important/);
    assert.match(css, /--nfc-w2-panel-header-top:\s*15px/);
    assert.match(
      css,
      /\.nfc-page-layout-ledger > \.nfc-data-panel > \.nfc-data-panel-header[\s\S]*padding:\s*var\(--nfc-w2-panel-header-top\) var\(--nfc-w2-panel-header-x\) var\(--nfc-w2-panel-header-bottom\)/
    );
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-data-panel-header[\s\S]*padding:\s*13px 14px 11px/);
  });

  test('glass treatment is constrained to utility and overlay surfaces', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*backdrop-filter:\s*blur\(22px\)/);
    assert.match(css, /\.ant-modal-content,[\s\S]*\.ant-drawer-content[\s\S]*backdrop-filter:\s*blur\(24px\)/);
    assert.match(css, /\.nfc-quarantine-page \.nfc-bulk-action-bar[\s\S]*backdrop-filter:\s*blur\(18px\)/);
    assert.doesNotMatch(css, /\.nfc-data-panel-body[^{]*\{[^}]*backdrop-filter/);
  });
});
