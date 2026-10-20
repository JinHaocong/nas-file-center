import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Pure White v2.1 dashboard and scan detail pass', () => {
  const dashboard = read('src/pages/Dashboard/index.tsx');
  const scans = read('src/pages/Scans/index.tsx');
  const shell = read('src/styles/console-v2.css');
  const scanCss = read('src/styles/console-v2-scans.css');

  test('Dashboard avoids counterfeit zero metrics during loading or API failure', () => {
    assert.ok(dashboard.includes("const summaryReady = !summaryLoading && !summaryError && Boolean(summary);"));
    assert.ok(dashboard.includes("summaryReady ? (summary?.indexed_files ?? 0).toLocaleString() : '—'"));
    assert.ok(dashboard.includes("summaryReady ? (summary?.plan_count ?? 0).toLocaleString() : '—'"));
    assert.ok(dashboard.includes("summaryError ? '暂不可用'"));
    assert.ok(dashboard.includes("summaryLoading ? '读取中…'"));
    assert.ok(dashboard.includes("{activeTaskCount ?? '—'}"));
  });

  test('Dashboard KPI, recent scans and worker summaries still use real APIs', () => {
    for (const source of [
      "dashboardApi.getSummary()", "scansApi.listScans(1, 5)", "tasksApi.listJobs(1, 5)",
      "queryKey: ['dashboardSummary']", "queryKey: ['recentScans']",
      "queryKey: ['recentTasks']", 'refetchInterval: 10000', 'refetchInterval: 5000',
      "navigate('/scans/' + item.id)", "navigate('/tasks')",
    ]) assert.ok(dashboard.includes(source), source);
    assert.ok(dashboard.includes('来自 API 的最新统计，非历史趋势预测'));
  });

  test('Dashboard has a precise white table hierarchy and accessible row focus', () => {
    assert.match(shell, /\.nfc-v2-data-table th\s*\{[^}]*padding:\s*12px 17px;[^}]*border-bottom:\s*1px solid var\(--v2-line\);/);
    assert.match(shell, /\.nfc-v2-data-table td\s*\{[^}]*padding:\s*13px 17px;[^}]*vertical-align:\s*middle;/);
    assert.match(shell, /\.nfc-v2-data-table tbody tr:hover,\s*\.nfc-v2-data-table tbody tr:focus-within\s*\{[^}]*background:\s*var\(--v2-indigo-soft\);/);
    assert.match(shell, /\.nfc-v2-row-link\s*\{[^}]*overflow-wrap:\s*anywhere;/);
  });

  test('Transparent Dashboard hero cancels legacy frosted header compositing', () => {
    const legacy = read('src/styles/v049-workspace.css');
    const entry = read('src/main.tsx');
    assert.match(legacy, /\\.nfc-page-header\\s*\\{[^}]*backdrop-filter:\\s*blur\\(16px\\) saturate\\(120%\\);/);
    assert.match(shell,
      /\\.nfc-v2-shell \\.nfc-v2-dashboard-hero \\.nfc-page-header\\s*\\{[^}]*background:\\s*transparent !important;[^}]*backdrop-filter:\\s*none;[^}]*-webkit-backdrop-filter:\\s*none;/);
    assert.ok(entry.indexOf("import './styles/console-v2.css';") >
      entry.indexOf("import './styles/v049-workspace.css';"),
    'Scoped transparent Dashboard hero must override historical page header blur');
  });

  test('Quick actions are a quiet single-column list, not a deck of nested cards', () => {
    assert.match(shell, /\.nfc-v2-quick-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/);
    assert.match(shell, /\.nfc-v2-dashboard \.nfc-quick-action\s*\{[^}]*flex-direction:\s*row;[^}]*border:\s*1px solid transparent !important;/);
    assert.match(shell, /\.nfc-v2-dashboard \.nfc-quick-action:hover,\s*\.nfc-v2-dashboard \.nfc-quick-action:focus-visible\s*\{/);
    assert.match(shell, /\.nfc-v2-dashboard \.nfc-quick-action-copy\s*\{[^}]*min-width:\s*0;/);
    assert.match(shell, /@media \(max-width: 767px\)/);
    assert.match(shell, /\.nfc-v2-dashboard-hero\s*\{\s*min-height:\s*0;\s*padding:\s*0 0 4px;/);
  });

  test('Scan history keeps server pagination, polling and guarded deletion', () => {
    for (const source of [
      "queryKey: ['scansList', page, pageSize]",
      'scansApi.listScans(page, pageSize)',
      "return hasActive ? 3000 : false",
      'scansApi.deleteScan(id)',
      'data?.items?.length === 1 && page > 1',
      'ScanDeleteButton',
      '<ConsolePagination page={page}',
      '<ResponsiveDataView',
      '<ScanCreateModal',
      '<DedupeDiagnosticModal',
    ]) assert.ok(scans.includes(source), source);
  });

  test('Scan screen uses localized real counts and only marks active polling when true', () => {
    assert.ok(scans.includes("const hasActiveScan = items.some(scan => scan.status === 'queued' || scan.status === 'running');"));
    assert.ok(scans.includes("{hasActiveScan && <span className=\"nfc-v2-scan-live-label\">进行中 · 自动刷新</span>}"));
    assert.ok(scans.includes("(data?.total ?? 0).toLocaleString()"));
    assert.ok(scans.includes('条记录'));
    for (const name of ['重复组', '重复文件', '可释放空间']) {
      assert.ok(scans.includes('<th scope="col" className="nfc-v2-scan-number">' + name + '</th>'), name);
    }
  });

  test('Scan table is neutral, scroll-contained and keyboard accessible', () => {
    assert.match(scanCss, /\.nfc-v2-scan-table-scroll\s*\{[^}]*overflow-x:\s*auto;/);
    assert.match(scanCss, /\.nfc-v2-scan-table thead th\s*\{[^}]*background:\s*var\(--v2-sidebar\);/);
    assert.match(scanCss, /\.nfc-v2-scan-table tbody tr:hover,\s*\.nfc-v2-scan-table tbody tr:focus-within\s*\{[^}]*background:\s*var\(--v2-indigo-soft\);/);
    assert.match(scanCss, /\.nfc-v2-scans-page \.nfc-v2-scan-name span\s*\{[^}]*overflow-wrap:\s*anywhere;/);
    assert.match(scanCss, /\.nfc-v2-scan-number\s*\{[^}]*font-variant-numeric:\s*tabular-nums;[^}]*text-align:\s*right;/);
    assert.ok(scanCss.includes('.nfc-v2-scans-page .nfc-v2-scan-table button:focus-visible'));
  });

  test('Scan mobile records and live indicator retain dark contrast and reduced motion', () => {
    assert.match(scanCss, /@media \(max-width: 767px\)[\s\S]*\.nfc-v2-scans-page \.nfc-scan-mobile-card\s*\{/);
    assert.match(scanCss, /\.nfc-v2-scans-page \.nfc-v2-scan-live-label\s*\{[^}]*background:\s*#edf6ef;/);
    assert.match(scanCss, /\[data-theme='dark'\] \.nfc-v2-scans-page \.nfc-v2-scan-live-label\s*\{[^}]*background:\s*#20392c;/);
    assert.match(scanCss, /@media \(prefers-reduced-motion: reduce\)/);
    assert.doesNotMatch(scanCss, /#2878ef|#83b5ff|linear-gradient/);
    assert.doesNotMatch(scanCss, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
  });

  test('Archive Recovery styling stays separately owned and no new global CSS override is introduced', () => {
    const archive = read('src/styles/console-v2-archive-recovery.css');
    const entry = read('src/main.tsx');
    assert.ok(archive.includes('.nfc-v2-shell .nfc-archive-recovery-page'));
    assert.ok(entry.includes("import './styles/console-v2-archive-recovery.css';"));
    assert.ok(entry.includes("import './styles/console-v2-scans.css';"));
    assert.doesNotMatch(entry, /v057|v058|pure-white\.css/);
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_pure_white_dashboard_scans.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_pure_white_dashboard_scans.test.js'));
  });
});
