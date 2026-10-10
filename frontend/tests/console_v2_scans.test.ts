import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getScanDeleteAvailability } from '../src/components/scans/scan_cleanup';
import { getPaginationState } from '../src/components/ui/paginationModel';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 scan history migration', () => {
  test('native scan list keeps server pagination, live polling and actual statistics', () => {
    const page = read('src/pages/Scans/index.tsx');
    for (const token of [
      "queryKey: ['scansList', page, pageSize]",
      'scansApi.listScans(page, pageSize)',
      'return hasActive ? 3000 : false',
      '<table className="nfc-v2-scan-table">',
      '<ConsolePagination',
      '<ConsoleEmpty',
      '<ResponsiveDataView',
      'nfc-scan-mobile-card',
      '<StatusBadge',
      'scan.total_groups',
      'scan.total_files_in_groups',
      'scan.reclaimable_bytes',
      'formatDateTime(scan.created_at)',
      'setPageSize(nextSize)',
      'setPage(1)',
    ]) assert.ok(page.includes(token), token);
    assert.doesNotMatch(page, /<Table\b|<Pagination\b|<Empty\b/);
    assert.deepEqual(getPaginationState(3, 20, 44), { pages: 3, current: 3, start: 41, end: 44 });
    assert.deepEqual(getPaginationState(1, 20, 0), { pages: 1, current: 1, start: 0, end: 0 });
  });

  test('scan deletion has correct terminal and dependent plan gates', () => {
    for (const status of ['queued', 'running']) {
      assert.equal(getScanDeleteAvailability({ status }).canDelete, false, status);
    }
    for (const status of ['completed', 'failed', 'cancelled']) {
      assert.equal(getScanDeleteAvailability({ status, has_dependent_plan: false }).canDelete, true, status);
      assert.equal(getScanDeleteAvailability({ status, has_dependent_plan: true }).canDelete, false, status);
    }
    const button = read('src/components/scans/ScanDeleteButton.tsx');
    for (const token of [
      'getScanDeleteAvailability(scan)', 'disabled={unavailable}',
      'if (!getScanDeleteAvailability(scan).canDelete || loading) return',
      '<ConsoleConfirmDialog', 'busy={loading}', 'disabled={!canDelete}',
      'onConfirm={confirmDelete}', 'onDelete()',
      '扫描元数据', '关联执行计划',
    ]) assert.ok(button.includes(token), token);
    assert.doesNotMatch(button, /from ['"]antd['"]|<Popconfirm\b|<Tooltip\b/);
  });

  test('mutation still invalidates scan and dashboard; deletion moves back from last page', () => {
    const page = read('src/pages/Scans/index.tsx');
    for (const token of [
      'scansApi.deleteScan(id)', "queryClient.invalidateQueries({ queryKey: ['scansList'] })",
      "queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] })",
      "data?.items?.length === 1 && page > 1",
      'deletingId === scan.id',
      'ScanDeleteButton',
    ]) assert.ok(page.includes(token), token);
    assert.match(page, /setPage\(previous => previous - 1\)/);
  });

  test('create scan form remains intact pending safe DirectoryPicker migration', () => {
    const page = read('src/pages/Scans/index.tsx');
    for (const token of [
      'Form.useForm()', 'DirectoryPicker', 'multiple placeholder=',
      "roots = values.roots.filter(Boolean)",
      "roots = values.roots.split('\\n')",
      "isolate: values.isolate || false",
      'min_size: values.min_size || null',
      'name_patterns_text', 'exclude_patterns_text',
      'scansApi.createScan(', 'createScanMutation.isPending',
      'ALLOWED_ROOTS', 'DedupeDiagnosticModal',
      "navigate(`/scans/${res.scan_job_id}`)",
    ]) assert.ok(page.includes(token), token);
    assert.match(page, /<Modal[\s\S]*<Form form=\{form\}/);
  });

  test('list distinguishes loading, empty and error; no stale results shown on API error', () => {
    const page = read('src/pages/Scans/index.tsx');
    for (const token of [
      'isError ? [] : data?.items || []',
      '扫描历史加载失败',
      '扫描历史加载失败',
      '正在读取扫描历史',
      '暂无扫描记录',
      '重新加载',
      'isError ?',
    ]) assert.ok(page.includes(token), token);
  });

  test('scan CSS is scoped and responsive in both themes', () => {
    const css = read('src/styles/console-v2-scans.css');
    const main = read('src/main.tsx');
    for (const selector of [
      '.nfc-v2-shell .nfc-v2-scans-page',
      '.nfc-v2-scan-table', '.nfc-scan-mobile-card',
      '@media (max-width: 767px)', 'prefers-reduced-motion: reduce',
    ]) assert.ok(css.includes(selector), selector);
    assert.ok(main.indexOf("import './styles/console-v2-scans.css';") >
      main.indexOf("import './styles/console-v2-task-overlays.css';"));
  });
});
