import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  getBulkSelectableEntryIds,
  getQuarantinePurgeAvailability,
} from '../src/components/quarantine/quarantine_rules';
import { quarantineApi } from '../src/api/quarantine';
import { api } from '../src/api/client';
import type { QuarantineEntry } from '../src/types';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const source = () => read('src/pages/Quarantine/index.tsx');

describe('Console v2 native Quarantine ledger / terminal cleanup', () => {
  test('no AntD widgets remain and list uses semantic responsive layout', () => {
    const s = source();
    for (const value of [
      '<PageHeader', '<DataPanel', '<ActionBar', '<ResponsiveDataView',
      '<ConsoleButton', '<ConsoleSelect', '<ConsolePagination',
      '<ConsoleEmpty', '<ConsoleConfirmDialog', 'useConsoleToast()',
      '<table className="nfc-v2-quarantine-table"', '<thead><tr>',
      '<tbody>{items.map(entry => (', 'nfc-quarantine-mobile-card',
      'className="nfc-v2-quarantine-checkbox"',
    ]) assert.ok(s.includes(value), value);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Pagination\b|Modal\.confirm|message\.(success|info|error|warning)/);
  });

  test('all active statuses are preserved in state filter and badge map', () => {
    const s = source();
    for (const state of ['preparing', 'active', 'restoring', 'purging', 'restored',
      'purged', 'inconsistent', 'abandoned', 'conflict', 'skipped']) {
      assert.ok(s.includes(state + ':'), state);
    }
    assert.ok(s.includes("label: '冲突 (conflict)'"));
  });

  test('only active page rows are selectable and selection persists across pagination', () => {
    const s = source();
    for (const value of [
      'getBulkSelectableEntryIds(items)', "record.state !== 'active'",
      "disabled={record.state !== 'active'}",
      'selectedEntryIds.includes(record.id)',
      'currentPageSelectableIds.every(id => selectedEntryIds.includes(id))',
      'toggleCurrentPage(event.target.checked)',
      'setSelectedEntryIds(current => checked',
      'Array.from(new Set([...current, ...currentPageSelectableIds]))',
      'aria-label="选择当前页所有 active 隔离条目"',
    ]) assert.ok(s.includes(value), value);
    const entries = [
      { id: 1, state: 'active' }, { id: 2, state: 'restored' },
      { id: 3, state: 'active' }, { id: 4, state: 'purging' },
    ] as QuarantineEntry[];
    assert.deepEqual(getBulkSelectableEntryIds(entries), [1, 3]);
  });

  test('filtered explicit ID resolver remains capped by backend API pagination and is fail-closed', () => {
    const s = source();
    for (const value of [
      'quarantineApi.resolveBulkFilteredEntryIds(snapshot)',
      'filterRequestEpoch.current !== ticket',
      'selectionInFlight.current', 'filterRequestEpoch.current += 1',
      '已选择当前筛选结果中的', 'clearBulkSelection()',
    ]) assert.ok(s.includes(value), value);
    const apiSource = read('src/api/quarantine.ts');
    assert.ok(apiSource.includes('entryIds.length > 5000'));
    assert.ok(apiSource.includes("entry.state === 'active'"));
  });

  test('changing search/state invalidates filtered selection, resets page and active IDs', () => {
    const s = source();
    for (const value of [
      'const handleSearch = () => {', 'const handleResetSearch = () => {',
      'const handleFilterChange = (value: string) => {',
      'invalidateFilteredRequests()', 'setPage(1);', 'clearBulkSelection()',
      'setActiveSearch(searchInput.trim())',
      'queryKey: [\'quarantineList\', page, pageSize, stateFilter, activeSearch]',
    ]) assert.ok(s.includes(value), value);
  });

  test('pagination uses current page/pageSize and preserves selection on normal page changes', () => {
    const s = source();
    assert.ok(s.includes('<ConsolePagination page={page} pageSize={pageSize}'));
    assert.ok(s.includes('total={quarantineData?.total || 0}'));
    assert.ok(s.includes('onChange={handlePageChange}'));
    assert.ok(s.includes('setPageSize(nextSize)'));
    assert.ok(s.includes('setPage(nextPage)'));
  });

  test('single restore and purge actions retain host gating and scoped dialogs', () => {
    const s = source();
    for (const value of [
      "const canRestore = record.state === 'active'",
      "const canPurge = record.state === 'active'",
      'disabled={isSafeMode}', 'disabled={isSafeMode || !isAdmin || !allowDelete}',
      'setRestoreEntry(record); setRestoreModalOpen(true);',
      'setPurgeEntry(record); setPurgeModalOpen(true);',
      '<RestoreModal entry={restoreEntry}', '<PurgeConfirmModal entry={purgeEntry}',
      'isAdmin={Boolean(isAdmin)}', 'allowMutation={!isSafeMode}', 'allowDelete={allowDelete}',
    ]) assert.ok(s.includes(value), value);
    assert.equal(getQuarantinePurgeAvailability(true, false, true, 'DELETE').canPurge, false);
  });

  test('bulk buttons require explicit ID selection and retain Plan lifecycle routing', () => {
    const s = source();
    for (const value of [
      'selectedEntryIds.length === 0 || isSafeMode',
      'selectedEntryIds.length === 0 || !isAdmin || isSafeMode || !allowDelete',
      'setBulkRestoreEntryIds([...selectedEntryIds])',
      'setBulkPurgeEntryIds([...selectedEntryIds])',
      'setBulkRestoreOpen(true)', 'setBulkPurgeOpen(true)',
      '<BulkRestoreModal', '<BulkPurgeModal', 'navigate(', 'navigate(\`/plans/\${plan.id}\`)',
      'Freeze', 'ALLOW_MUTATION=false', 'ALLOW_DELETE=false',
    ]) assert.ok(s.includes(value), value);
  });

  test('terminal states alone can invoke record deletion and nonadmin is blocked', () => {
    const s = source();
    for (const value of [
      "const canDeleteRecord = ['restored', 'purged', 'abandoned', 'conflict'].includes(record.state)",
      "const TERMINAL_STATES = ['restored', 'purged', 'abandoned', 'conflict']",
      "if (!isAdmin || !canDeleteRecord",
      "if (!TERMINAL_STATES.some(state => state === record.state)) return;",
      'if (!isAdmin) toast.error(\'仅系统管理员允许删除隔离记录\')',
      "record.state === 'restored' && (isSafeMode || !allowDelete)",
    ]) assert.ok(s.includes(value), value);
  });

  test('terminal single cleanup confirmation discloses private-trash impact and audit retention', () => {
    const s = source();
    for (const value of [
      'const SINGLE_RECORD_WARNING',
      '.nas-file-center-trash',
      '恢复后的正式文件不会被删除',
      '审计事件仍会保留',
      'cleanupTarget.record.id', "kind: 'single'",
      'await deleteRecordMutation.mutateAsync(target.record.id)',
      "queryKey: ['auditEvents']",
    ]) assert.ok(s.includes(value), value);
  });

  test('terminal bulk record cleanup resolves snapshot before separate explicit confirmation', () => {
    const s = source();
    for (const value of [
      'resolveTerminalCleanupFilteredEntryIds(snapshot)',
      "setCleanupTarget({ kind: 'filtered', entryIds: [...entryIds] })",
      'terminalRequestEpoch.current !== ticket',
      'setResolvingTerminalRecords(true)',
      'terminalInFlight.current = true',
      "target.kind === 'single'",
      'await bulkDeleteRecordsMutation.mutateAsync([...target.entryIds])',
      '任一条无法证明安全时整批拒绝',
    ]) assert.ok(s.includes(value), value);
    const apiSource = read('src/api/quarantine.ts');
    assert.ok(apiSource.includes("['restored', 'purged', 'abandoned', 'conflict'].includes(entry.state)"));
    assert.ok(apiSource.includes("confirmation: 'DELETE_RECORDS'"));
  });

  test('destructive confirm cannot be dismissed during in-flight requests', () => {
    const s = source();
    for (const value of [
      'const cleanupInFlight = useRef(false)',
      'if (!cleanupTarget || !isAdmin || cleanupInFlight.current || cleanupBusy) return',
      'cleanupInFlight.current = true',
      'setCleanupBusy(true)', 'setCleanupBusy(false)',
      'cleanupInFlight.current = false',
      'if (!next && !cleanupInFlight.current && !cleanupBusy) setCleanupTarget(null)',
      '<ConsoleConfirmDialog open={cleanupTarget !== null} onOpenChange={closeCleanup}',
      'confirmText="删除记录" busy={cleanupBusy}',
    ]) assert.ok(s.includes(value), value);
    const dialog = read('src/components/ui/ConsoleConfirmDialog.tsx');
    assert.ok(dialog.includes('onPointerDownOutside={event => event.preventDefault()}'));
  });

  test('queued WorkJob record cleanup stays visibly queued rather than being reported as deleted', () => {
    const s = source();
    for (const value of [
      "result.status === 'queued' && result.work_job_id",
      "queryKey: ['tasks']",
      'Worker 将回收已恢复记录的 .nas-file-center-trash 私有副本',
      '已进入任务中心',
    ]) assert.ok(s.includes(value), value);
  });

  test('safety errors and empty/loading/error pages remain native and actionable', () => {
    const s = source();
    for (const value of [
      'getStructuredApiError(err)', 'toast.error(',
      'if (!isAdmin)', 'isError &&', 'isLoading &&',
      '<ConsoleEmpty title="暂无隔离条目"',
      'void refetch()', '获取隔离区列表失败',
    ]) assert.ok(s.includes(value), value);
  });

  test('new CSS owns native desktop/table/mobile states and accessibility focus', () => {
    const css = read('src/styles/console-v2-quarantine-ledger.css');
    for (const value of [
      '.nfc-v2-quarantine-ledger', '.nfc-v2-quarantine-table',
      '.nfc-v2-quarantine-bulk-actions', '.nfc-v2-quarantine-search',
      '.nfc-v2-quarantine-checkbox', '.nfc-v2-quarantine-mobile-list',
      "data-theme='dark'", 'focus-visible', 'max-width:767px',
      'prefers-reduced-motion:reduce', 'min-height:44px',
    ]) assert.ok(css.includes(value), value);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-quarantine-ledger.css';"));
  });
});
