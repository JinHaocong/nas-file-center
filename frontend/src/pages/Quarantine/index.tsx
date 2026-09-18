import React, { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  Modal,
  Pagination,
  Select,
  Table,
  Tooltip,
  message,
} from 'antd';
import { DeleteOutlined, LockOutlined, ReloadOutlined, SearchOutlined, UndoOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { quarantineApi } from '../../api/quarantine';
import { getStructuredApiError } from '../../api/errors';
import { settingsApi } from '../../api/domain';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { QuarantineEntry, QuarantineState } from '../../types';
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

const STATE_CONFIG: Record<QuarantineState, { label: string; status: string }> = {
  preparing: { label: '准备中', status: 'queued' },
  active: { label: '已隔离', status: 'paused' },
  restoring: { label: '恢复中', status: 'running' },
  purging: { label: '清除中', status: 'executing' },
  restored: { label: '已恢复', status: 'completed' },
  purged: { label: '已清除', status: 'cancelled' },
  inconsistent: { label: '异常不一致', status: 'failed' },
  abandoned: { label: '已废弃', status: 'stale' },
  skipped: { label: '已跳过', status: 'skipped' },
};

export const QuarantinePage: React.FC = () => {
  useTitle('文件隔离区');
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
  const [resolvingPurgedRecords, setResolvingPurgedRecords] = useState(false);

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: () => settingsApi.getSettings() });
  const isSafeMode = !settings?.allow_mutation;
  const allowDelete = Boolean(settings?.allow_delete);

  const { data: quarantineData, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['quarantineList', page, pageSize, stateFilter, activeSearch],
    queryFn: () => quarantineApi.list({ page, pageSize, state: stateFilter, query: activeSearch }),
  });

  const deleteRecordMutation = useMutation({
    mutationFn: (entryId: number) => quarantineApi.deleteRecord(entryId),
    onSuccess: (_, entryId) => {
      message.success(`隔离记录 #${entryId} 已删除（仅删除数据库记录）`);
      queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
      refetch();
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '删除隔离记录失败');
    },
  });

  const bulkDeleteRecordsMutation = useMutation({
    mutationFn: (entryIds: number[]) => quarantineApi.bulkDeleteRecords(entryIds),
    onSuccess: (result) => {
      message.success(`已删除 ${result.deleted_count} 条已清除隔离记录`);
      queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
      refetch();
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '批量删除隔离记录失败');
    },
  });

  const clearBulkSelection = () => { setSelectedEntryIds([]); setSelectionNotice(''); };
  const handleSearch = () => { setActiveSearch(searchInput.trim()); setPage(1); clearBulkSelection(); };
  const handleResetSearch = () => { setSearchInput(''); setActiveSearch(''); setPage(1); clearBulkSelection(); };
  const currentPageSelectableIds = getBulkSelectableEntryIds(quarantineData?.items || []);

  const handleSelectCurrentPage = () => {
    if (currentPageSelectableIds.length === 0) { message.info('当前页没有可批量操作的 active 条目'); return; }
    setSelectedEntryIds((current) => Array.from(new Set([...current, ...currentPageSelectableIds])));
    setSelectionNotice(`已选择当前页 ${currentPageSelectableIds.length} 个 active 条目；翻页后选择仍保留`);
  };

  const handleSelectAllFiltered = async () => {
    setResolvingFilteredSelection(true);
    try {
      const explicitIds = await quarantineApi.resolveBulkFilteredEntryIds({ state: stateFilter, query: activeSearch });
      setSelectedEntryIds(explicitIds);
      setSelectionNotice(`已选择当前筛选结果中的 ${explicitIds.length} 个 active 条目（已解析为显式 ID）`);
      if (explicitIds.length === 0) message.info('当前筛选结果中没有 active 条目');
    } catch (err: any) {
      clearBulkSelection();
      message.error(err?.message || '解析当前筛选结果的显式 ID 失败');
    } finally {
      setResolvingFilteredSelection(false);
    }
  };

  const toggleSelected = (id: number, checked: boolean) => {
    setSelectedEntryIds((current) => checked ? Array.from(new Set([...current, id])) : current.filter((v) => v !== id));
    setSelectionNotice(checked ? '已更新显式 active 条目选择' : '');
  };

  const rowSelection = {
    selectedRowKeys: selectedEntryIds,
    preserveSelectedRowKeys: true,
    onChange: (keys: React.Key[]) => {
      setSelectedEntryIds(keys.map(Number));
      setSelectionNotice(keys.length > 0 ? `已明确选择 ${keys.length} 个 active 条目` : '');
    },
    getCheckboxProps: (record: QuarantineEntry) => ({ disabled: record.state !== 'active', name: `quarantine-entry-${record.id}` }),
  };

  const handleDeleteFilteredPurgedRecords = async () => {
    if (!isAdmin) {
      message.error('仅系统管理员允许删除隔离记录');
      return;
    }
    setResolvingPurgedRecords(true);
    try {
      const entryIds = await quarantineApi.resolvePurgedFilteredEntryIds({
        state: stateFilter,
        query: activeSearch,
      });
      if (entryIds.length === 0) {
        message.info('当前筛选结果中没有可删除的已清除记录');
        return;
      }
      Modal.confirm({
        title: `批量删除 ${entryIds.length} 条已清除记录？`,
        content: '只删除数据库中的隔离历史记录，不会执行文件系统删除。服务端仍会逐条确认 state=purged 且隔离 payload 路径不存在；任一条不满足时整批拒绝。',
        okText: '删除记录',
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: () => bulkDeleteRecordsMutation.mutateAsync(entryIds),
      });
    } catch (err) {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '解析已清除记录失败');
    } finally {
      setResolvingPurgedRecords(false);
    }
  };

  const items = quarantineData?.items || [];

  const confirmDeleteRecord = (record: QuarantineEntry) => {
    Modal.confirm({
      title: `删除隔离记录 #${record.id}？`,
      content: '仅删除已经永久清除后的数据库记录；不会再次操作文件系统，审计事件仍会保留。',
      okText: '删除记录',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => deleteRecordMutation.mutateAsync(record.id),
    });
  };

  const actionButtons = (record: QuarantineEntry, compact = true) => {
    const canRestore = record.state === 'active';
    const canPurge = record.state === 'active';
    const canDeleteRecord = record.state === 'purged';
    if (!canRestore && !canPurge && !canDeleteRecord) return <span className="nfc-table-muted">—</span>;
    return (
      <div className="nfc-row-actions">
        {canRestore && (
          <Tooltip title={isSafeMode ? '只读保护模式 (ALLOW_MUTATION=false) 生效中，禁止恢复' : '恢复到原路径或指定路径'}>
            <Button size={compact ? 'small' : 'middle'} type="text" icon={<UndoOutlined />} disabled={isSafeMode} onClick={() => { setRestoreEntry(record); setRestoreModalOpen(true); }}>恢复</Button>
          </Tooltip>
        )}
        {canPurge && (
          <Tooltip title={!isAdmin ? '仅系统管理员允许永久清除' : isSafeMode ? '只读保护模式 (ALLOW_MUTATION=false) 生效中，禁止清除' : !allowDelete ? '系统禁用永久删除 (ALLOW_DELETE=false)' : '按普通文件删除（unlink）语义清除 NFC 拥有的隔离区路径'}>
            <Button size={compact ? 'small' : 'middle'} type="text" danger icon={<DeleteOutlined />} disabled={isSafeMode || !isAdmin || !allowDelete} onClick={() => { setPurgeEntry(record); setPurgeModalOpen(true); }}>清除</Button>
          </Tooltip>
        )}
        {canDeleteRecord && (
          <Tooltip title={!isAdmin ? '仅系统管理员允许删除已清除记录' : '仅删除数据库记录；不会再次触碰文件系统'}>
            <Button
              size={compact ? 'small' : 'middle'}
              type="text"
              danger
              icon={<DeleteOutlined />}
              disabled={!isAdmin || deleteRecordMutation.isPending}
              onClick={() => confirmDeleteRecord(record)}
            >
              删除记录
            </Button>
          </Tooltip>
        )}
      </div>
    );
  };

  const columns = [
    { title: '编号', dataIndex: 'id', key: 'id', width: 72, render: (id: number) => <span className="nfc-mono">#{id}</span> },
    { title: '原始路径', dataIndex: 'original_path', key: 'original_path', render: (p: string) => <CodePath value={p} /> },
    { title: '隔离区路径', dataIndex: 'quarantine_path', key: 'quarantine_path', render: (p: string) => <CodePath value={p} muted /> },
    { title: '大小', dataIndex: 'size', key: 'size', width: 108, render: (v: number) => v > 0 ? formatBytes(v) : '—' },
    { title: '状态', dataIndex: 'state', key: 'state', width: 118, render: (state: QuarantineState) => <StatusBadge status={STATE_CONFIG[state]?.status || 'queued'} label={STATE_CONFIG[state]?.label || state} /> },
    { title: '隔离时间', dataIndex: 'quarantined_at', key: 'quarantined_at', width: 168, render: (v: string | null) => <span className="nfc-table-meta">{v ? formatDateTime(v) : '—'}</span> },
    { title: '过期时间', dataIndex: 'expires_at', key: 'expires_at', width: 168, render: (v: string | null) => <span className="nfc-table-meta">{v ? formatDateTime(v) : '永久保留'}</span> },
    { title: '操作', key: 'action', width: 144, render: (_: unknown, record: QuarantineEntry) => actionButtons(record) },
  ];

  return (
    <div className="nfc-operations-page">
      <PageHeader
        eyebrow="SAFETY"
        title="文件隔离区"
        description="Quarantine-first 文件安全边界。恢复遵循零覆盖语义；永久删除同时受管理员、ALLOW_MUTATION 与 ALLOW_DELETE 约束。"
        actions={<ActionBar compact><Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>刷新</Button></ActionBar>}
      />

      {isSafeMode && <Alert className="nfc-page-alert" message="只读安全保护模式生效中" description="系统当前以 ALLOW_MUTATION=false 运行。所有文件移动与写入已被锁定，恢复与清除操作当前不可用。" type="info" showIcon icon={<LockOutlined />} />}

      <DataPanel title="隔离文件" description="筛选、显式选择并生成恢复或永久删除计划。" action={<span className="nfc-panel-count">{quarantineData?.total ?? 0} entries</span>} className="nfc-panel-flush">
        <ActionBar className="nfc-filter-bar nfc-quarantine-filter-bar">
          <Input className="nfc-search-input" placeholder="搜索原始路径或隔离路径..." value={searchInput} onChange={(e)=>setSearchInput(e.target.value)} onPressEnter={handleSearch} prefix={<SearchOutlined />} allowClear />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
          {activeSearch && <Button onClick={handleResetSearch}>重置</Button>}
          <Select
            value={stateFilter}
            onChange={(val)=>{setStateFilter(val);setPage(1);clearBulkSelection();}}
            options={[
              {label:'全部状态',value:'all'},{label:'已隔离 (active)',value:'active'},{label:'已恢复 (restored)',value:'restored'},
              {label:'已清除 (purged)',value:'purged'},{label:'准备中 (preparing)',value:'preparing'},
              {label:'异常 (inconsistent)',value:'inconsistent'},{label:'已废弃 (abandoned)',value:'abandoned'},
            ]}
          />
        </ActionBar>

        <ActionBar className="nfc-bulk-action-bar">
          <span className={`nfc-selection-count ${selectedEntryIds.length > 0 ? 'nfc-selection-count-active' : ''}`}>已选择 {selectedEntryIds.length}</span>
          <Button onClick={handleSelectCurrentPage} disabled={currentPageSelectableIds.length===0}>选择本页 active ({currentPageSelectableIds.length})</Button>
          <Button onClick={handleSelectAllFiltered} loading={resolvingFilteredSelection} disabled={resolvingFilteredSelection}>选择筛选全部 active</Button>
          <Button onClick={clearBulkSelection} disabled={selectedEntryIds.length===0}>清空选择</Button>
          <Tooltip title={isSafeMode ? 'ALLOW_MUTATION=false，禁止生成批量恢复计划' : undefined}><Button icon={<UndoOutlined />} disabled={selectedEntryIds.length===0 || isSafeMode} onClick={()=>{setBulkRestoreEntryIds([...selectedEntryIds]);setBulkRestoreOpen(true);}}>批量恢复</Button></Tooltip>
          <Tooltip title={selectedEntryIds.length===0 ? '请先明确选择至少一个 active 条目' : !isAdmin ? '仅系统管理员允许永久删除' : isSafeMode ? 'ALLOW_MUTATION=false，禁止生成删除计划' : !allowDelete ? 'ALLOW_DELETE=false，服务端禁止永久删除' : '先 Preview，再输入 DELETE 生成 unlink_v1 Draft'}>
            <Button danger icon={<DeleteOutlined />} disabled={selectedEntryIds.length===0 || !isAdmin || isSafeMode || !allowDelete} onClick={()=>{setBulkPurgeEntryIds([...selectedEntryIds]);setBulkPurgeOpen(true);}}>批量永久删除</Button>
          </Tooltip>
          <Tooltip title={!isAdmin ? '仅系统管理员允许删除隔离记录' : '删除当前筛选结果中的全部 purged 数据库记录；不执行文件系统操作'}>
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={!isAdmin || resolvingPurgedRecords || bulkDeleteRecordsMutation.isPending}
              loading={resolvingPurgedRecords || bulkDeleteRecordsMutation.isPending}
              onClick={handleDeleteFilteredPurgedRecords}
            >
              批量删除已清除记录
            </Button>
          </Tooltip>
        </ActionBar>

        {selectionNotice && <Alert className="nfc-selection-notice" type="info" showIcon message={selectionNotice} />}

        <ResponsiveDataView
          desktop={<Table dataSource={items} columns={columns} rowKey="id" rowSelection={rowSelection} loading={isLoading} scroll={{x:1240}} pagination={{current:page,pageSize,total:quarantineData?.total||0,showSizeChanger:true,pageSizeOptions:['10','20','50','100'],onChange:(p,ps)=>{setPage(p);setPageSize(ps);}}} />}
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {items.length===0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无隔离条目" /> : items.map((entry)=>(
                  <article className="nfc-quarantine-mobile-card" key={entry.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-quarantine-mobile-id"><Checkbox checked={selectedEntryIds.includes(entry.id)} disabled={entry.state!=='active'} onChange={(e)=>toggleSelected(entry.id,e.target.checked)} /><span className="nfc-mono">#{entry.id}</span></div>
                      <StatusBadge status={STATE_CONFIG[entry.state]?.status || 'queued'} label={STATE_CONFIG[entry.state]?.label || entry.state} />
                    </div>
                    <div className="nfc-plan-item-paths">
                      <div className="nfc-plan-item-path-row"><span>原始路径</span><CodePath value={entry.original_path} /></div>
                      <div className="nfc-plan-item-path-row"><span>隔离路径</span><CodePath value={entry.quarantine_path} muted /></div>
                    </div>
                    <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                      <span>大小 <b>{entry.size>0 ? formatBytes(entry.size) : '—'}</b></span>
                      <span>隔离 <b>{entry.quarantined_at ? formatDateTime(entry.quarantined_at) : '—'}</b></span>
                      <span>过期 <b>{entry.expires_at ? formatDateTime(entry.expires_at) : '永久保留'}</b></span>
                    </div>
                    <div className="nfc-mobile-record-actions">{actionButtons(entry,false)}</div>
                  </article>
                ))}
              </div>
              <div className="nfc-mobile-pagination"><Pagination current={page} pageSize={pageSize} total={quarantineData?.total||0} showSizeChanger pageSizeOptions={['10','20','50','100']} onChange={(p,ps)=>{setPage(p);setPageSize(ps);}} /></div>
            </>
          }
        />
      </DataPanel>

      <RestoreModal entry={restoreEntry} open={restoreModalOpen} onClose={()=>{setRestoreModalOpen(false);setRestoreEntry(null);}} onSuccess={()=>refetch()} isSafeMode={isSafeMode} />
      <PurgeConfirmModal entry={purgeEntry} open={purgeModalOpen} onClose={()=>{setPurgeModalOpen(false);setPurgeEntry(null);}} onSuccess={()=>refetch()} isAdmin={Boolean(isAdmin)} allowMutation={!isSafeMode} allowDelete={allowDelete} />
      <BulkRestoreModal open={bulkRestoreOpen} entryIds={bulkRestoreEntryIds} isSafeMode={isSafeMode} onClose={()=>{setBulkRestoreOpen(false);setBulkRestoreEntryIds([]);}} onPlanCreated={(plan)=>{setBulkRestoreOpen(false);setBulkRestoreEntryIds([]);clearBulkSelection();navigate(`/plans/${plan.id}`);}} />
      <BulkPurgeModal open={bulkPurgeOpen} entryIds={bulkPurgeEntryIds} isAdmin={Boolean(isAdmin)} allowMutation={!isSafeMode} allowDelete={allowDelete} onClose={()=>{setBulkPurgeOpen(false);setBulkPurgeEntryIds([]);}} onPlanCreated={(plan)=>{setBulkPurgeOpen(false);setBulkPurgeEntryIds([]);clearBulkSelection();navigate(`/plans/${plan.id}`);}} />
    </div>
  );
};
