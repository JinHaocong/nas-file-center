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


describe('v0.4.8 detail polish pass', () => {
  test('detail layer loads last and leaves approved navigation untouched', () => {
    const main = read('src/main.tsx');
    assert.match(
      main,
      /import '\.\/styles\/v048-pages\.css';[\s\S]*import '\.\/styles\/v048-detail\.css';/
    );

    const css = read('src/styles/v048-detail.css');
    assert.doesNotMatch(css, /\.nfc-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-sidebar-menu(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-brand(?:\b|\.)/);
  });

  test('command rail is route-aware instead of using static template copy', () => {
    const header = read('src/components/Header.tsx');
    assert.match(header, /useLocation/);
    assert.match(header, /resolveWorkspaceContext/);
    assert.match(header, /高级去重工作台/);
    assert.match(header, /执行计划详情/);
    assert.match(header, /工作流编辑器/);
    assert.doesNotMatch(header, /Local operations/);
  });

  test('command rail status copy is compact while tooltips retain detail', () => {
    const safe = read('src/components/SafeModeBadge.tsx');
    const worker = read('src/components/WorkerStatusBadge.tsx');
    assert.match(safe, />\s*永久删除\s*</);
    assert.match(safe, />\s*隔离写入\s*</);
    assert.match(safe, />\s*只读\s*</);
    assert.match(worker, /队列 \{activeJobs\}/);
    assert.match(worker, />\s*队列空闲\s*</);
  });

  test('status island restores semantic safety and queue tones', () => {
    const css = read('src/styles/v048-detail.css');
    assert.match(css, /\.nfc-header-status[\s\S]*border-radius: 999px/);
    assert.match(css, /\.nfc-header-status-badge\.is-safe[\s\S]*var\(--nfc-success\)/);
    assert.match(css, /\.nfc-header-status-badge\.is-danger[\s\S]*var\(--nfc-danger\)/);
    assert.match(css, /\.nfc-header-status-badge\.is-processing[\s\S]*var\(--nfc-premium-accent\)/);
  });

  test('descriptions, alerts and empty states use the refined editorial treatment', () => {
    const css = read('src/styles/v048-detail.css');
    assert.match(css, /\.nfc-responsive-descriptions[\s\S]*border-radius: 0 !important/);
    assert.match(css, /\.nfc-page-alert\.ant-alert,[\s\S]*border-left: 2px solid/);
    assert.match(css, /\.nfc-data-panel \.ant-empty[\s\S]*padding: 36px 16px/);
  });

  test('row actions remain accessible while becoming quieter at rest', () => {
    const css = read('src/styles/v048-detail.css');
    assert.match(css, /\.nfc-row-actions[\s\S]*opacity: 0\.78/);
    assert.match(css, /\.nfc-row-actions:focus-within[\s\S]*opacity: 1/);
    assert.match(css, /@media \(max-width: 767px\)[\s\S]*\.nfc-row-actions[\s\S]*opacity: 1/);
  });

  test('live status motion respects reduced-motion preference', () => {
    const css = read('src/styles/v048-detail.css');
    assert.match(css, /@keyframes nfc-detail-live-pulse/);
    assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none/);
  });
});


describe('v0.4.9 full workspace overhaul', () => {
  test('loads after every v0.4.8 layer', () => {
    const main = read('src/main.tsx');
    assert.match(
      main,
      /import '\.\/styles\/v048-detail\.css';[\s\S]*import '\.\/styles\/v049-workspace\.css';/
    );
  });

  test('does not override the approved left navigation', () => {
    const css = read('src/styles/v049-workspace.css');
    assert.doesNotMatch(css, /\.nfc-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-sidebar-menu(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-brand(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-nav-group-label(?:\b|\.)/);
  });

  test('resets global right-workspace gutter and content width', () => {
    const css = read('src/styles/v049-workspace.css');
    assert.match(css, /--nfc-v49-content-max:\s*1480px/);
    assert.match(css, /\.nfc-page-content[\s\S]*padding:\s*28px 34px 56px/);
    assert.match(css, /\.nfc-page-content > \*[\s\S]*var\(--nfc-v49-content-max\)/);
  });

  test('covers every major routed workspace family', () => {
    const css = read('src/styles/v049-workspace.css');
    for (const selector of [
      '.nfc-dashboard-page',
      '.nfc-indexes-page',
      '.nfc-scans-page',
      '.nfc-advanced-dedupe-page',
      '.nfc-path-match-page',
      '.nfc-rename-page',
      '.nfc-batch-page',
      '.nfc-organizer-page',
      '.nfc-organizer-preview-page',
      '.nfc-workflows-page',
      '.nfc-workflow-builder-page',
      '.nfc-plans-page',
      '.nfc-plan-detail-page',
      '.nfc-quarantine-page',
      '.nfc-tasks-page',
      '.nfc-audit-page',
      '.nfc-system-controls-page',
      '.nfc-login-shell',
    ]) {
      assert.ok(css.includes(selector), `missing v0.4.9 coverage for ${selector}`);
    }
  });

  test('unifies shared table, form, modal, drawer and directory picker density', () => {
    const css = read('src/styles/v049-workspace.css');
    assert.match(css, /\.nfc-data-panel \.ant-table-tbody > tr[\s\S]*height:\s*44px/);
    assert.match(css, /\.nfc-app-shell \.ant-form-item[\s\S]*margin-bottom:\s*16px/);
    assert.match(css, /\.ant-modal \.ant-modal-body[\s\S]*padding:\s*16px 18px 18px/);
    assert.match(css, /\.ant-drawer \.ant-drawer-body[\s\S]*padding:\s*15px/);
    assert.match(css, /\.nfc-directory-item\.ant-list-item[\s\S]*min-height:\s*46px/);
  });

  test('has explicit desktop, tablet and mobile spacing systems', () => {
    const css = read('src/styles/v049-workspace.css');
    assert.match(css, /@media \(min-width: 1600px\)/);
    assert.match(css, /@media \(max-width: 1199px\)/);
    assert.match(css, /@media \(max-width: 767px\)/);
    assert.match(css, /@media \(max-width: 420px\)/);
  });

  test('settings, workflow and dedupe have dedicated composition rather than generic card fallback', () => {
    const css = read('src/styles/v049-workspace.css');
    assert.match(css, /\.nfc-system-controls-page \.nfc-settings-grid/);
    assert.match(css, /\.nfc-workflow-builder-page \.nfc-workflow-step-card\.is-expanded/);
    assert.match(css, /\.nfc-advanced-dedupe-page \.nfc-dedupe-editor-wrap/);
  });
});
