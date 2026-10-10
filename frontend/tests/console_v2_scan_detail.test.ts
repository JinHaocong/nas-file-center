import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getPaginationState } from '../src/components/ui/paginationModel';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 Scan Detail duplicate group inspector', () => {
  test('scan details use semantic tables and preserve mobile grouped member cards', () => {
    const page = read('src/pages/Scans/ScanDetail.tsx');
    for (const token of [
      '<table className="nfc-v2-groups-table">', '<table className="nfc-v2-group-member-table">',
      'nfc-v2-group-member-row', 'nfc-duplicate-group-mobile-card', 'nfc-duplicate-member-list',
      'ResponsiveDataView', 'ResponsiveDescriptions', 'PageHeader', 'DataPanel', 'CodePath',
      'StatusBadge', '<ConsolePagination', '<ConsoleEmpty',
    ]) assert.ok(page.includes(token), token);
    assert.doesNotMatch(page, /from ['"]antd['"]|from ['"]@ant-design\/icons['"]|<Table\b|<Pagination\b|<Tooltip\b/);
  });

  test('file members preserve root, full/relative paths, sizes and full hash access', () => {
    const page = read('src/pages/Scans/ScanDetail.tsx');
    for (const token of [
      'group.members.map(member =>', 'root #{member.root_id}', 'member.relative_path',
      'member.path', 'formatBytes(member.size)', 'group.content_hash.slice(0, 18)',
      'title={group.content_hash}', 'group.file_size', 'group.member_count',
      'group.reclaimable_bytes', 'aria-expanded={expanded}',
      "aria-controls={'nfc-group-members-' + group.id}",
      'onClick={() => toggleGroup(group.id)}',
      'setExpandedGroupIds([])',
    ]) assert.ok(page.includes(token), token);
  });

  test('server pagination and 3-second live scan polling remain unchanged', () => {
    const page = read('src/pages/Scans/ScanDetail.tsx');
    for (const token of [
      "queryKey: ['scanDetail', scanId]",
      'scansApi.getScanDetail(scanId)',
      "return status === 'queued' || status === 'running' ? 3000 : false",
      "queryKey: ['scanGroups', scanId, page, pageSize]",
      'scansApi.getScanGroups(scanId, page, pageSize)',
      "enabled: validScanId && scan?.status === 'completed'",
      'setPageSize(nextSize)', 'setPage(1)', 'pageSizes={[10, 20, 50, 100]}',
    ]) assert.ok(page.includes(token), token);
    assert.deepEqual(getPaginationState(4, 20, 62), { current: 4, pages: 4, start: 61, end: 62 });
  });

  test('plan generation remains gated, with no direct NAS writes or new authority', () => {
    const page = read('src/pages/Scans/ScanDetail.tsx');
    for (const token of [
      "scan.status === 'completed' && scan.total_groups > 0",
      'DedupePlanModal', 'Advanced Dedupe', "navigate('/scans/' + scan.id + '/dedupe')",
      'DedupeDiagnosticModal', 'ScanDeleteButton key={scan.id}',
      'deleteScanMutation.isPending', 'queryClient.invalidateQueries',
      'Plan 生命周期', '只读快照',
      'scan.has_dependent_plan',
    ]) assert.ok(page.includes(token), token);
    assert.doesNotMatch(page, /allow_mutation\s*=|deleteFiles\(|executePlan\(/);
  });

  test('detail/group load failures are distinct from legitimate zero-result states', () => {
    const page = read('src/pages/Scans/ScanDetail.tsx');
    for (const token of [
      'scanError', 'scanFetchError', 'validScanId',
      'groupsError ? [] : groupsData?.items || []',
      'groupsError ? null : groupsData?.total',
      '重复文件组加载失败', '暂无重复文件组',
      '扫描任务不存在', '无法加载扫描详情',
      'groupsFetchError', 'refetchGroups()',
    ]) assert.ok(page.includes(token), token);
    assert.match(page, /enabled: validScanId && scan\?\.status === 'completed'/);
    assert.match(page, /Number\.isSafeInteger\(scanId\) && scanId > 0/);
  });

  test('scoped Scan Detail CSS is loaded after Scan History and honors mobile/reduced motion', () => {
    const main = read('src/main.tsx');
    const css = read('src/styles/console-v2-scan-detail.css');
    assert.ok(main.indexOf("import './styles/console-v2-scan-detail.css';") >
      main.indexOf("import './styles/console-v2-scans.css';"));
    for (const token of [
      '.nfc-v2-scan-detail-page', '.nfc-v2-groups-table', '.nfc-v2-group-member-table',
      '.nfc-v2-group-expand:focus-visible', '.nfc-duplicate-group-mobile-card',
      "[data-theme='dark']", '@media (max-width: 767px)', 'prefers-reduced-motion: reduce',
    ]) assert.ok(css.includes(token), token);
  });
});
