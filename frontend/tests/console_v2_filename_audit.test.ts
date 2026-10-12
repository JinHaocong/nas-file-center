import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { FilenameAuditPreview, FilenameAuditRow } from '../src/api/domain';
import {
  buildFilenameAuditRequest, buildFilenameAuditCsv, buildFilenameAuditPlanItems,
  canCreateFilenameAuditPlan, filterFilenameAuditRows, isFilenameAuditRepairable,
} from '../src/utils/filenameAuditSafety';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const safe: FilenameAuditRow = {
  name: ' good.txt ', path: '/data/ good.txt ',
  issues: ['edge_whitespace', 'windows_trailing_dot_space'],
  suggested_target: '/data/good.txt', suggestion_block_reason: null,
};
const unsafe: FilenameAuditRow = {
  name: 'invoice.pdf.exe', path: '/data/invoice.pdf.exe',
  issues: ['suspicious_double_extension'],
  suggested_target: null, suggestion_block_reason: 'manual review',
};
const report = (rows: FilenameAuditRow[] = [safe, unsafe]): FilenameAuditPreview => ({
  parent: '/data', scanned: 3, checked_regular_files: 2, ignored_entries: 1,
  issues_total: 3, counts: { edge_whitespace: 1 }, items: rows, total: rows.length,
});

describe('Console v2 Filename Audit — native guarded migration', () => {
  test('preserves exact one-field server preview request and rejects empty directory', () => {
    assert.deepEqual(buildFilenameAuditRequest('/data/Foo '), { parent: '/data/Foo ' });
    assert.deepEqual(buildFilenameAuditRequest(' /data/Foo'), { parent: ' /data/Foo' });
    assert.equal(buildFilenameAuditRequest(''), null);
    assert.equal(buildFilenameAuditRequest('  '), null);
  });

  test('preserves all report issues and filters only server-suggested safe repairs', () => {
    assert.equal(filterFilenameAuditRows(report().items, 'all').length, 2);
    assert.deepEqual(filterFilenameAuditRows(report().items, 'fixable'), [safe]);
    assert.deepEqual(filterFilenameAuditRows(report().items, 'suspicious_double_extension'), [unsafe]);
    assert.deepEqual(filterFilenameAuditRows(report().items, 'long_name'), []);
    assert.equal(isFilenameAuditRepairable(unsafe), false);
    assert.equal(isFilenameAuditRepairable(safe), true);
  });

  test('selected-only Draft creates exact rename payload without Execute/Freeze', () => {
    assert.deepEqual(buildFilenameAuditPlanItems(report(), report(), [safe.path]), [
      { operation: 'rename', source: '/data/ good.txt ', target: '/data/good.txt' },
    ]);
    assert.equal(buildFilenameAuditPlanItems(report(), report(), []), null);
    assert.equal(buildFilenameAuditPlanItems(report(), report(), [unsafe.path]), null);
    assert.equal(buildFilenameAuditPlanItems(report(), report(), ['/data/other']), null);
  });

  test('server re-scan fails closed on changed target, missing row, parent or issue detail', () => {
    assert.equal(buildFilenameAuditPlanItems(report(), report([{ ...safe, suggested_target: '/data/changed.txt' }]), [safe.path]), null);
    assert.equal(buildFilenameAuditPlanItems(report(), report([unsafe]), [safe.path]), null);
    assert.equal(buildFilenameAuditPlanItems(report(), { ...report(), parent: '/other' }, [safe.path]), null);
    assert.equal(buildFilenameAuditPlanItems(report(), report([{ ...safe, issues: ['edge_whitespace'] }]), [safe.path]), null);
    assert.equal(buildFilenameAuditPlanItems(report(), report([{ ...safe, name: 'changed' }]), [safe.path]), null);
  });

  test('duplicate sources, targets and selected source-target chains cannot produce a Draft', () => {
    assert.equal(buildFilenameAuditPlanItems(report(), report(), [safe.path, safe.path]), null);
    const second = { ...safe, name: ' duplicate.txt ', path: '/data/ duplicate.txt ' };
    const conflict = { ...second, suggested_target: safe.suggested_target };
    assert.equal(buildFilenameAuditPlanItems(report([safe, conflict]),
      report([safe, conflict]), [safe.path, conflict.path]), null);
    const chained = { ...second, path: safe.suggested_target, suggested_target: '/data/duplicate.txt' };
    assert.equal(buildFilenameAuditPlanItems(report([safe, chained]),
      report([safe, chained]), [safe.path, chained.path]), null);
  });

  test('missing/identity/blocked/no-whitespace suggestions never enable Plan', () => {
    for (const altered of [
      { ...safe, suggested_target: null },
      { ...safe, suggested_target: safe.path },
      { ...safe, suggested_target: '' },
      { ...safe, suggestion_block_reason: 'conflict' },
      { ...safe, issues: ['unicode_non_nfc'] as FilenameAuditRow['issues'] },
    ]) {
      assert.equal(isFilenameAuditRepairable(altered), false);
      assert.equal(buildFilenameAuditPlanItems(report([altered]), report([altered]), [altered.path]), null);
    }
  });

  test('Plan control only enables for current, nonempty, unblocked selection', () => {
    assert.equal(canCreateFilenameAuditPlan(report(), 'preview-key', [safe.path], false), true);
    assert.equal(canCreateFilenameAuditPlan(report(), null, [safe.path], false), false);
    assert.equal(canCreateFilenameAuditPlan(report(), 'preview-key', [], false), false);
    assert.equal(canCreateFilenameAuditPlan(null, 'preview-key', [safe.path], false), false);
    assert.equal(canCreateFilenameAuditPlan(report(), 'preview-key', [unsafe.path], false), false);
    assert.equal(canCreateFilenameAuditPlan(report(), 'preview-key', [safe.path], true), false);
  });

  test('CSV preserves headers, only passed rows, escapes quotes, and neutralizes formulas', () => {
    const csv = buildFilenameAuditCsv([{ ...safe, name: ' =HYPERLINK("x")',
      path: ' +CMD /data', suggestion_block_reason: '@danger' }]);
    assert.ok(csv.startsWith('\uFEFF"filename","absolute_path"'));
    assert.ok(csv.includes('"\' =HYPERLINK(""x"")"'));
    assert.ok(csv.includes('"\' +CMD /data"'));
    assert.ok(csv.includes('"\'@danger"'));
    assert.ok(csv.includes('\r\n'));
    assert.equal(csv.includes('invoice.pdf.exe'), false);
  });

  test('page uses native primitives, unified pagination, and explicit read-only Draft API', () => {
    const source = read('src/pages/FilenameAudit/index.tsx');
    for (const token of [
      '<DirectoryPicker value={parent}', 'filenameAuditApi.preview',
      'plansApi.createPlan', 'buildFilenameAuditPlanItems(captured, fresh, selectedPaths)',
      'buildFilenameAuditRequest(parent)', 'requestTicket.current !== ticket',
      'activePreviewKey.current !== key', 'invalidatePreview();',
      'planGuard.current', 'previewGuard.current', "kind: 'rename'",
      "'/plans/' + created.id",
      '<ConsoleButton', '<ConsolePagination', '<ConsoleEmpty',
      '<ResponsiveDataView', '<CodePath', 'getPaginationState',
      'visiblePage.map(', 'togglePage(', 'type="checkbox"', 'type="select"',
      '导出 CSV', 'buildFilenameAuditCsv(rows)', '仅首尾普通空格',
    ]) {
      assert.ok(source.includes(token) || (token === 'type="select"' && source.includes('<select value={filter}')),
        token);
    }
    assert.doesNotMatch(source, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Form\b|<Pagination\b|<Tag\b/);
    assert.doesNotMatch(source, /executePlan|freezePlan|validatePlan|window\.location/);
  });

  test('CSS is scoped for dark theme, mobile/focus and reduced motion', () => {
    const css = read('src/styles/console-v2-filename-audit.css');
    for (const symbol of [
      '.nfc-v2-filename-audit', '.nfc-v2-filename-table',
      '.nfc-v2-filename-issues', '.nfc-v2-filename-mobile',
      '.nfc-v2-filename-filter', "[data-theme='dark']", ':focus-visible',
      '@media (max-width:767px)', 'min-height:44px',
      '@media (prefers-reduced-motion:reduce)',
    ]) assert.ok(css.includes(symbol), symbol);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-filename-audit.css';"));
  });
});
