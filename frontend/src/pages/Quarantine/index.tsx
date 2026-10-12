import React, { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { quarantineApi } from '../../api/quarantine';
import { getStructuredApiError } from '../../api/errors';
import { settingsApi } from '../../api/domain';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import type { QuarantineEntry, QuarantineState } from '../../types';
import { getBulkSelectableEntryIds } from '../../components/quarantine/quarantine_rules';
import { RestoreModal } from './RestoreModal';
import { PurgeConfirmModal } from './PurgeConfirmModal';
import { BulkRestoreModal } from './BulkRestoreModal';
import { BulkPurgeModal } from './BulkPurgeModal';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleSelect } from '../../components/ui/ConsoleSelect';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const STATE_CONFIG: Record<QuarantineState, { label: string; status: string }> = {
  preparing: { label: '准备中', status: 'queued' },
  active: { label: '已隔离', status: 'paused' },
  restoring: { label: '恢复中', status: 'running' },
  purging: { label: '清除中', status: 'executing' },
  restored: { label: '已恢复', status: 'completed' },
  purged: { label: '已清除', status: 'cancelled' },
  inconsistent: { label: '异常不一致', status: 'failed' },
  abandoned: { label: '已废弃', status: 'stale' },
  conflict: { label: '冲突', status: 'failed' },
  skipped: { label: '已跳过', status: 'skipped' },
};

const TERMINAL_STATES = ['restored', 'purged', 'abandoned', 'conflict'] as const;
const STATE_FILTER_OPTIONS = [
  { label: '全部状态', value: 'all' },
  { label: '已隔离 (active)', value: 'active' },
  { label: '已恢复 (restored)', value: 'restored' },
  { label: '已清除 (purged)', value: 'purged' },
  { label: '准备中 (preparing)', value: 'preparing' },
  { label: '异常 (inconsistent)', value: 'inconsistent' },
  { label: '已废弃 (abandoned)', value: 'abandoned' },
  { label: '冲突 (conflict)', value: 'conflict' },
] as const;

type RecordCleanupTarget =
  | { kind: 'single'; record: QuarantineEntry }
  | { kind: 'filtered'; entryIds: number[] };

const SINGLE_RECORD_WARNING =
  '支持 restored / purged / abandoned / conflict。若为 restored，会验证恢复目标后清理 .nas-file-center-trash 中该 entry 的 NFC 私有事务副本，再删除记录；恢复后的正式文件不会被删除。审计事件仍会保留。';
const FILTERED_RECORD_WARNING =
  '支持 restored / purged / abandoned / conflict。restored 会先验证恢复目标仍保持原身份，再删除 .nas-file-center-trash 中该 entry 的 NFC 私有事务副本并释放空间，最后删除记录；恢复后的正式文件不会被删除。其他终态仍按 metadata-only 规则清理。任一条无法证明安全时整批拒绝。';

export const QuarantinePage: React.FC = () => {
  useTitle('文件隔离区');
  const toast = useConsoleToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [stateFilter, setStateFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [restoreEntry, setRestoreEntry] = useState<QuarantineEntry | null>(null);
  const [restoreModalOpen, setRestoreModalOpen] = useState(false);
  const [purgeEntry, setPurgeEntry] = useState<QuarantineEntry | null>(null);
  const [purgeModalOpen, setPurgeModalOpen] = useState(false);
  const [selectedEntryIds, setSelectedEntryIds] = useState<number[]>([]);
  const [selectionNotice, setSelectionNotice] = useState('');
  const [resolvingFilteredSelection, setResolvingFilteredSelection] = useState(false);
  const [bulkRestoreEntryIds, setBulkRestoreEntryIds] = useState<number[]>([]);
  const [bulkRestoreOpen, setBulkRestoreOpen] = useState(false);
  const [bulkPurgeEntryIds, setBulkPurgeEntryIds] = useState<number[]>([]);
  const [bulkPurgeOpen, setBulkPurgeOpen] = useState(false);
  const [resolvingTerminalRecords, setResolvingTerminalRecords] = useState(false);
  const [cleanupTarget, setCleanupTarget] = useState<RecordCleanupTarget | null>(null);
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const cleanupInFlight = useRef(false);
  const filterRequestEpoch = useRef(0);
  const terminalRequestEpoch = useRef(0);
  const selectionInFlight = useRef(false);
  const terminalInFlight = useRef(false);

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: () => settingsApi.getSettings() });
  const isSafeMode = !settings?.allow_mutation;
  const allowDelete = Boolean(settings?.allow_delete);
  const { data: quarantineData, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['quarantineList', page, pageSize, stateFilter, activeSearch],
    queryFn: () => quarantineApi.list({ page, pageSize, state: stateFilter, query: activeSearch }),
  });

  const deleteRecordMutation = useMutation({
    mutationFn: (entryId: number) => quarantineApi.deleteRecord(entryId),
    onSuccess: (result, entryId) => {
      if (result.status === 'queued' && result.work_job_id) {
        toast.success('已恢复记录 #' + entryId + ' 的安全清理任务 #' + result.work_job_id + ' 已进入任务中心');
        void queryClient.invalidateQueries({ queryKey: ['tasks'] });
        return;
      }
      toast.success('隔离记录 #' + entryId + ' 已删除');
      void queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      void queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
      void refetch();
    },
    onError: (err: unknown) => {
      const structured = getStructuredApiError(err);
      toast.error(structured.message || '删除隔离记录失败');
    },
  });

  const bulkDeleteRecordsMutation = useMutation({
    mutationFn: (entryIds: number[]) => quarantineApi.bulkDeleteRecords(entryIds),
    onSuccess: result => {
      if (result.status === 'queued' && result.work_job_id) {
        toast.success('安全清理任务 #' + result.work_job_id + ' 已进入任务中心；Worker 将回收已恢复记录的 .nas-file-center-trash 私有副本');
        void queryClient.invalidateQueries({ queryKey: ['tasks'] });
        return;
      }
      toast.success('已删除 ' + (result.deleted_count ?? 0) + ' 条隔离记录');
      void queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      void queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
      void refetch();
    },
    onError: (err: unknown) => {
      const structured = getStructuredApiError(err);
      toast.error(structured.message || '批量删除隔离记录失败');
    },
  });

  const clearBulkSelection = () => { filterRequestEpoch.current += 1; setSelectedEntryIds([]); setSelectionNotice(''); };
  const invalidateFilteredRequests = () => {
    filterRequestEpoch.current += 1;
    terminalRequestEpoch.current += 1;
  };
  const handleSearch = () => {
    invalidateFilteredRequests();
    setActiveSearch(searchInput.trim());
    setPage(1);
    clearBulkSelection();
  };
  const handleResetSearch = () => {
    invalidateFilteredRequests();
    setSearchInput('');
    setActiveSearch('');
    setPage(1);
    clearBulkSelection();
  };
  const handleFilterChange = (value: string) => {
    invalidateFilteredRequests();
    setStateFilter(value);
    setPage(1);
    clearBulkSelection();
  };
  const handlePageChange = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };

  const items = quarantineData?.items || [];
  const currentPageSelectableIds = getBulkSelectableEntryIds(items);
  const currentPageAllSelected = currentPageSelectableIds.length > 0 &&
    currentPageSelectableIds.every(id => selectedEntryIds.includes(id));

  const handleSelectCurrentPage = () => {
    if (currentPageSelectableIds.length === 0) {
      toast.info('当前页没有可批量操作的 active 条目');
      return;
    }
    filterRequestEpoch.current += 1;
    setSelectedEntryIds(current => Array.from(new Set([...current, ...currentPageSelectableIds])));
    setSelectionNotice('已选择当前页 ' + currentPageSelectableIds.length + ' 个 active 条目；翻页后选择仍保留');
  };
  const toggleCurrentPage = (checked: boolean) => {
    filterRequestEpoch.current += 1;
    setSelectedEntryIds(current => checked
      ? Array.from(new Set([...current, ...currentPageSelectableIds]))
      : current.filter(id => !currentPageSelectableIds.includes(id)));
    setSelectionNotice(checked ? '已选择当前页 active 条目（翻页后选择仍保留）' : '已取消当前页 active 条目选择');
  };
  const toggleSelected = (record: QuarantineEntry, checked: boolean) => {
    if (record.state !== 'active') return;
    filterRequestEpoch.current += 1;
    setSelectedEntryIds(current => checked
      ? Array.from(new Set([...current, record.id]))
      : current.filter(id => id !== record.id));
    setSelectionNotice(checked ? '已更新显式 active 条目选择' : '');
  };
  const handleSelectAllFiltered = async () => {
    if (selectionInFlight.current) return;
    selectionInFlight.current = true;
    const ticket = ++filterRequestEpoch.current;
    const snapshot = { state: stateFilter, query: activeSearch };
    setResolvingFilteredSelection(true);
    try {
      const explicitIds = await quarantineApi.resolveBulkFilteredEntryIds(snapshot);
      if (filterRequestEpoch.current !== ticket) return;
      setSelectedEntryIds(explicitIds);
      setSelectionNotice('已选择当前筛选结果中的 ' + explicitIds.length + ' 个 active 条目（已解析为显式 ID）');
      if (explicitIds.length === 0) toast.info('当前筛选结果中没有 active 条目');
    } catch (err: unknown) {
      if (filterRequestEpoch.current !== ticket) return;
      clearBulkSelection();
      toast.error(getStructuredApiError(err).message || '解析当前筛选结果的显式 ID 失败');
    } finally {
      selectionInFlight.current = false;
      setResolvingFilteredSelection(false);
    }
  };

  const handleDeleteFilteredTerminalRecords = async () => {
    if (!isAdmin || terminalInFlight.current || cleanupInFlight.current || bulkDeleteRecordsMutation.isPending) {
      if (!isAdmin) toast.error('仅系统管理员允许删除隔离记录');
      return;
    }
    terminalInFlight.current = true;
    const ticket = ++terminalRequestEpoch.current;
    const snapshot = { state: stateFilter, query: activeSearch };
    setResolvingTerminalRecords(true);
    try {
      const entryIds = await quarantineApi.resolveTerminalCleanupFilteredEntryIds(snapshot);
      if (terminalRequestEpoch.current !== ticket) return;
      if (entryIds.length === 0) {
        toast.info('当前筛选结果中没有可删除的终态记录');
        return;
      }
      setCleanupTarget({ kind: 'filtered', entryIds: [...entryIds] });
    } catch (err: unknown) {
      if (terminalRequestEpoch.current === ticket) {
        toast.error(getStructuredApiError(err).message || '解析终态记录失败');
      }
    } finally {
      terminalInFlight.current = false;
      setResolvingTerminalRecords(false);
    }
  };

  const confirmDeleteRecord = (record: QuarantineEntry) => {
    const canDeleteRecord = ['restored', 'purged', 'abandoned', 'conflict'].includes(record.state);
    if (!isAdmin || !canDeleteRecord || cleanupInFlight.current ||
        (record.state === 'restored' && (isSafeMode || !allowDelete))) return;
    setCleanupTarget({ kind: 'single', record });
  };
  const handleConfirmCleanup = async () => {
    if (!cleanupTarget || !isAdmin || cleanupInFlight.current || cleanupBusy) return;
    if (cleanupTarget.kind === 'single') {
      const record = cleanupTarget.record;
      if (!TERMINAL_STATES.some(state => state === record.state)) return;
      if (record.state === 'restored' && (isSafeMode || !allowDelete)) return;
    }
    const target = cleanupTarget;
    cleanupInFlight.current = true;
    setCleanupBusy(true);
    try {
      if (target.kind === 'single') {
        await deleteRecordMutation.mutateAsync(target.record.id);
      } else {
        await bulkDeleteRecordsMutation.mutateAsync([...target.entryIds]);
      }
      setCleanupTarget(null);
    } catch {
      // onError reports the failure; retain the explicit confirmation for retry.
    } finally {
      cleanupInFlight.current = false;
      setCleanupBusy(false);
    }
  };
  const closeCleanup = (next: boolean) => {
    if (!next && !cleanupInFlight.current && !cleanupBusy) setCleanupTarget(null);
  };

  const actionButtons = (record: QuarantineEntry, compact = true) => {
    const canRestore = record.state === 'active';
    const canPurge = record.state === 'active';
    const canDeleteRecord = ['restored', 'purged', 'abandoned', 'conflict'].includes(record.state);
    if (!canRestore && !canPurge && !canDeleteRecord) {
      return <span className="nfc-table-muted">—</span>;
    }
    const size = compact ? 'sm' : 'md';
    return (
      <div className="nfc-row-actions nfc-v2-quarantine-actions">
        {canRestore && (
          <span title={isSafeMode ? '只读保护模式 (ALLOW_MUTATION=false) 生效中，禁止恢复' : '恢复到原路径或指定路径'}>
            <ConsoleButton size={size} variant="ghost" leadingIcon={<ConsoleIcon name="archive" size={15} />}
              disabled={isSafeMode}
              onClick={() => { setRestoreEntry(record); setRestoreModalOpen(true); }}>恢复</ConsoleButton>
          </span>
        )}
        {canPurge && (
          <span title={!isAdmin ? '仅系统管理员允许永久清除' : isSafeMode ? '只读保护模式 (ALLOW_MUTATION=false) 生效中，禁止清除' : !allowDelete ? '系统禁用永久删除 (ALLOW_DELETE=false)' : '按普通文件删除（unlink）语义清除 NFC 拥有的隔离区路径'}>
            <ConsoleButton size={size} variant="ghost" leadingIcon={<ConsoleIcon name="trash" size={15} />}
              disabled={isSafeMode || !isAdmin || !allowDelete}
              onClick={() => { setPurgeEntry(record); setPurgeModalOpen(true); }}>清除</ConsoleButton>
          </span>
        )}
        {canDeleteRecord && (
          <span title={!isAdmin ? '仅系统管理员允许删除终态记录' : record.state === 'restored'
            ? '验证恢复目标后，清理 NFC 私有隔离副本并删除记录；不会删除恢复后的正式文件'
            : '删除终态数据库记录；服务端会确认不存在剩余 payload / anchor / transaction artifacts'}>
            <ConsoleButton size={size} variant="ghost" leadingIcon={<ConsoleIcon name="trash" size={15} />}
              disabled={!isAdmin || cleanupBusy || deleteRecordMutation.isPending ||
                (record.state === 'restored' && (isSafeMode || !allowDelete))}
              onClick={() => confirmDeleteRecord(record)}>删除记录</ConsoleButton>
          </span>
        )}
      </div>
    );
  };

  const checkedEntry = (record: QuarantineEntry) => (
    <input type="checkbox" className="nfc-v2-quarantine-checkbox"
      aria-label={'选择隔离条目 #' + record.id}
      checked={record.state === 'active' && selectedEntryIds.includes(record.id)}
      disabled={record.state !== 'active'}
      onChange={event => toggleSelected(record, event.target.checked)} />
  );
  const renderStatus = (state: QuarantineState) => (
    <StatusBadge status={STATE_CONFIG[state]?.status || 'queued'} label={STATE_CONFIG[state]?.label || state} />
  );
  const hasResults = items.length > 0;
  const cleanupDescription = cleanupTarget?.kind === 'filtered'
    ? FILTERED_RECORD_WARNING
    : SINGLE_RECORD_WARNING;
  const cleanupTitle = cleanupTarget?.kind === 'filtered'
    ? '批量删除 ' + cleanupTarget.entryIds.length + ' 条终态记录？'
    : '删除隔离记录 #' + (cleanupTarget?.kind === 'single' ? cleanupTarget.record.id : '') + '？';

  return (
    <div className="nfc-operations-page nfc-quarantine-page nfc-page-layout-ledger nfc-v2-quarantine-ledger">
      <PageHeader eyebrow="Safety boundary" title="文件隔离区"
        description="Quarantine-first 文件安全边界。恢复遵循零覆盖语义；永久删除同时受管理员、ALLOW_MUTATION 与 ALLOW_DELETE 约束。"
        actions={<ActionBar compact>
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void refetch(); }} loading={isFetching}>刷新</ConsoleButton>
        </ActionBar>}
      />
      {isSafeMode && <div className="nfc-v2-quarantine-notice" role="status">
        <ConsoleIcon name="lock" size={18} />
        <span><strong>只读安全保护模式生效中。</strong> 系统当前以 ALLOW_MUTATION=false 运行。所有文件移动与写入已被锁定，恢复与清除操作当前不可用。</span>
      </div>}

      <DataPanel title="隔离文件" description="筛选、显式选择并生成恢复或永久删除计划。"
        action={<span className="nfc-panel-count">{quarantineData?.total ?? 0} entries</span>}
        className="nfc-panel-flush" variant="dense">
        <div className="nfc-quarantine-command-center nfc-v2-quarantine-command-center">
          <ActionBar className="nfc-filter-bar nfc-quarantine-filter-bar nfc-v2-quarantine-filters">
            <form className="nfc-v2-quarantine-search" onSubmit={event => { event.preventDefault(); handleSearch(); }}>
              <label htmlFor="quarantine-search">搜索路径</label>
              <div className="nfc-v2-quarantine-search-shell">
                <ConsoleIcon name="search" size={16} />
                <input id="quarantine-search" type="search" placeholder="搜索原始路径或隔离路径..."
                  value={searchInput} onChange={event => setSearchInput(event.target.value)} />
              </div>
              <ConsoleButton variant="primary" type="submit">搜索</ConsoleButton>
              {activeSearch && <ConsoleButton onClick={handleResetSearch}>重置</ConsoleButton>}
            </form>
            <ConsoleSelect id="quarantine-state-filter" label="隔离状态" value={stateFilter}
              options={STATE_FILTER_OPTIONS} onChange={handleFilterChange} />
          </ActionBar>
          <ActionBar className="nfc-bulk-action-bar nfc-v2-quarantine-bulk-actions">
            <span className={'nfc-selection-count' + (selectedEntryIds.length ? ' nfc-selection-count-active' : '')}
              aria-live="polite">已选择 {selectedEntryIds.length}</span>
            <ConsoleButton size="sm" disabled={currentPageSelectableIds.length === 0}
              onClick={handleSelectCurrentPage}>选择本页 active ({currentPageSelectableIds.length})</ConsoleButton>
            <ConsoleButton size="sm" loading={resolvingFilteredSelection}
              disabled={resolvingFilteredSelection} onClick={() => { void handleSelectAllFiltered(); }}>
              选择筛选全部 active
            </ConsoleButton>
            <ConsoleButton size="sm" disabled={selectedEntryIds.length === 0} onClick={clearBulkSelection}>
              清空选择
            </ConsoleButton>
            <span title={isSafeMode ? 'ALLOW_MUTATION=false，禁止生成批量恢复计划' : undefined}>
              <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="archive" size={15} />}
                disabled={selectedEntryIds.length === 0 || isSafeMode}
                onClick={() => { setBulkRestoreEntryIds([...selectedEntryIds]); setBulkRestoreOpen(true); }}>
                批量恢复
              </ConsoleButton>
            </span>
            <span title={!isAdmin ? '仅系统管理员允许永久删除' : isSafeMode ? 'ALLOW_MUTATION=false，禁止生成删除计划' : !allowDelete ? 'ALLOW_DELETE=false，服务端禁止永久删除' : '先 Preview，再输入 DELETE 生成 unlink_v1 Draft'}>
              <ConsoleButton size="sm" variant="danger" leadingIcon={<ConsoleIcon name="trash" size={15} />}
                disabled={selectedEntryIds.length === 0 || !isAdmin || isSafeMode || !allowDelete}
                onClick={() => { setBulkPurgeEntryIds([...selectedEntryIds]); setBulkPurgeOpen(true); }}>
                批量永久删除
              </ConsoleButton>
            </span>
            <span title={!isAdmin ? '仅系统管理员允许删除隔离记录' : '批量清理当前筛选结果中的 restored / purged / abandoned / conflict；restored 会额外释放 .nas-file-center-trash 私有副本空间'}>
              <ConsoleButton size="sm" variant="danger" leadingIcon={<ConsoleIcon name="trash" size={15} />}
                disabled={!isAdmin || resolvingTerminalRecords || cleanupBusy || bulkDeleteRecordsMutation.isPending}
                loading={resolvingTerminalRecords}
                onClick={() => { void handleDeleteFilteredTerminalRecords(); }}>
                批量删除记录
              </ConsoleButton>
            </span>
          </ActionBar>
          {selectionNotice && <div className="nfc-v2-quarantine-selection-notice nfc-selection-notice" role="status">
            <ConsoleIcon name="info" size={16} />{selectionNotice}
          </div>}
        </div>

        {isError && <div className="nfc-v2-quarantine-error" role="alert">
          <strong>获取隔离区列表失败</strong>
          <p>{getStructuredApiError(error).message || '服务暂时不可用，请重试。'}</p>
          <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重试</ConsoleButton>
        </div>}
        {!isError && isLoading && <div className="nfc-v2-quarantine-loading" role="status">正在读取隔离区条目…</div>}
        {!isError && !isLoading && !hasResults && <ConsoleEmpty title="暂无隔离条目"
          description="可以调整筛选状态或搜索条件后重试。" />}
        {!isError && !isLoading && hasResults && (
          <>
            <ResponsiveDataView
              desktop={<div className="nfc-v2-quarantine-table-scroll">
                <table className="nfc-v2-quarantine-table">
                  <thead><tr>
                    <th scope="col" className="nfc-v2-quarantine-check-cell">
                      <input type="checkbox" className="nfc-v2-quarantine-checkbox"
                        aria-label="选择当前页所有 active 隔离条目"
                        checked={currentPageAllSelected}
                        disabled={currentPageSelectableIds.length === 0}
                        onChange={event => toggleCurrentPage(event.target.checked)} />
                    </th>
                    <th scope="col">编号</th><th scope="col">原始路径</th>
                    <th scope="col">隔离区路径</th><th scope="col">大小</th>
                    <th scope="col">状态</th><th scope="col">隔离时间</th>
                    <th scope="col">过期时间</th><th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(entry => (
                    <tr key={entry.id}>
                      <td className="nfc-v2-quarantine-check-cell">{checkedEntry(entry)}</td>
                      <td className="nfc-mono">#{entry.id}</td>
                      <td><CodePath value={entry.original_path} /></td>
                      <td><CodePath value={entry.quarantine_path} muted /></td>
                      <td>{entry.size > 0 ? formatBytes(entry.size) : '—'}</td>
                      <td>{renderStatus(entry.state)}</td>
                      <td className="nfc-table-meta">{entry.quarantined_at ? formatDateTime(entry.quarantined_at) : '—'}</td>
                      <td className="nfc-table-meta">{entry.expires_at ? formatDateTime(entry.expires_at) : '永久保留'}</td>
                      <td>{actionButtons(entry)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<div className="nfc-mobile-record-list nfc-v2-quarantine-mobile-list">
                {items.map(entry => (
                  <article className="nfc-quarantine-mobile-card" key={entry.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-quarantine-mobile-id">
                        {checkedEntry(entry)}<span className="nfc-mono">#{entry.id}</span>
                      </div>
                      {renderStatus(entry.state)}
                    </div>
                    <div className="nfc-plan-item-paths">
                      <div className="nfc-plan-item-path-row"><span>原始路径</span><CodePath value={entry.original_path} /></div>
                      <div className="nfc-plan-item-path-row"><span>隔离路径</span><CodePath value={entry.quarantine_path} muted /></div>
                    </div>
                    <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                      <span>大小 <b>{entry.size > 0 ? formatBytes(entry.size) : '—'}</b></span>
                      <span>隔离 <b>{entry.quarantined_at ? formatDateTime(entry.quarantined_at) : '—'}</b></span>
                      <span>过期 <b>{entry.expires_at ? formatDateTime(entry.expires_at) : '永久保留'}</b></span>
                    </div>
                    <div className="nfc-mobile-record-actions">{actionButtons(entry, false)}</div>
                  </article>
                ))}
              </div>}
            />
            <ConsolePagination page={page} pageSize={pageSize} total={quarantineData?.total || 0}
              onChange={handlePageChange} />
          </>
        )}
      </DataPanel>

      <ConsoleConfirmDialog open={cleanupTarget !== null} onOpenChange={closeCleanup}
        title={cleanupTitle} description={cleanupDescription}
        confirmText="删除记录" busy={cleanupBusy}
        disabled={!isAdmin || !cleanupTarget ||
          (cleanupTarget.kind === 'single' && cleanupTarget.record.state === 'restored' &&
            (isSafeMode || !allowDelete))}
        onConfirm={() => { void handleConfirmCleanup(); }} />
      <RestoreModal entry={restoreEntry} open={restoreModalOpen}
        onClose={() => { setRestoreModalOpen(false); setRestoreEntry(null); }}
        onSuccess={() => { void refetch(); }} isSafeMode={isSafeMode} />
      <PurgeConfirmModal entry={purgeEntry} open={purgeModalOpen}
        onClose={() => { setPurgeModalOpen(false); setPurgeEntry(null); }}
        onSuccess={() => { void refetch(); }} isAdmin={Boolean(isAdmin)}
        allowMutation={!isSafeMode} allowDelete={allowDelete} />
      <BulkRestoreModal open={bulkRestoreOpen} entryIds={bulkRestoreEntryIds}
        isSafeMode={isSafeMode} onClose={() => { setBulkRestoreOpen(false); setBulkRestoreEntryIds([]); }}
        onPlanCreated={plan => {
          setBulkRestoreOpen(false); setBulkRestoreEntryIds([]); clearBulkSelection();
          navigate(`/plans/${plan.id}`);
        }} />
      <BulkPurgeModal open={bulkPurgeOpen} entryIds={bulkPurgeEntryIds}
        isAdmin={Boolean(isAdmin)} allowMutation={!isSafeMode} allowDelete={allowDelete}
        onClose={() => { setBulkPurgeOpen(false); setBulkPurgeEntryIds([]); }}
        onPlanCreated={plan => {
          setBulkPurgeOpen(false); setBulkPurgeEntryIds([]); clearBulkSelection();
          navigate(`/plans/${plan.id}`);
        }} />
    </div>
  );
};
