import React, { useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { indexesApi, mediaApi, plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import type { CorruptDeletePreview, MediaAsset } from '../../types/media';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { DataPanel } from '../../components/ui/DataPanel';
import { MetricCard } from '../../components/ui/MetricCard';
import { PageHeader } from '../../components/ui/PageHeader';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const formatBytes = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes, index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return (value >= 100 || index === 0 ? value.toFixed(0) : value.toFixed(1)) + ' ' + units[index];
};
const formatDuration = (seconds: number | null) => {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return seconds.toFixed(1) + 's';
  return Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
};

const integrityBadge = (record: MediaAsset) => {
  const status = record.integrity_status;
  const label = record.integrity_status === 'healthy' ? '正常' :
    record.integrity_status === 'corrupt' ? '损坏' : '未知';
  return <span className={'nfc-v2-media-status is-' + status}
    title={record.integrity_detail || record.integrity_reason_code || undefined}>
    <ConsoleIcon name={status === 'healthy' ? 'check-circle' : status === 'corrupt' ? 'shield-check' : 'info'} size={14} />
    {label}
  </span>;
};
const verificationBadge = (record: MediaAsset) => {
  const labels = {
    unverified: '未建立基线', baseline: '基线已建立',
    verified: 'SHA256 通过', changed: '内容变化', unknown: '无法校验',
  } as const;
  return <span className={'nfc-v2-media-status is-' + record.verification_status}
    title={record.verification_detail || record.verification_reason_code || undefined}>
    <ConsoleIcon name={record.verification_status === 'verified' ? 'check-circle' :
      record.verification_status === 'changed' ? 'shield-check' : 'info'} size={14} />
    {labels[record.verification_status]}
  </span>;
};

interface RootOption { value: string; label: string; disabled: boolean; }
interface QueueDialogProps {
  open: boolean;
  kind: 'analyze' | 'verify';
  roots: string[];
  options: RootOption[];
  busy: boolean;
  onClose: () => void;
  onChange: (roots: string[]) => void;
  onConfirm: () => void;
}
const QueueDialog: React.FC<QueueDialogProps> = ({
  open, kind, roots, options, busy, onClose, onChange, onConfirm,
}) => {
  const isVerify = kind === 'verify';
  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next && !busy) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
        <Dialog.Content className="nfc-v2-dialog nfc-overlay-modal nfc-v2-media-queue-dialog"
          onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon">
              <ConsoleIcon name={isVerify ? 'shield-check' : 'file-search'} size={20} />
            </span>
            <div>
              <Dialog.Title>{isVerify ? 'SHA256 完整性校验' : '启动媒体分析'}</Dialog.Title>
              <Dialog.Description className="nfc-v2-media-queue-description">
                {isVerify ? '读取源文件建立或比较不可自动覆盖的 SHA256 基线，不修改源文件。' :
                  '独立于普通文件索引的媒体探测，在后台队列运行。'}
              </Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dialog-close" aria-label="关闭媒体任务窗口"
              disabled={busy} onClick={onClose}><ConsoleIcon name="x" size={18} /></button>
          </header>
          <div className="nfc-v2-media-queue-body">
            <p className="nfc-form-note">{isVerify
              ? '首次运行在索引身份匹配时建立 SHA256 基线；之后按 dev/inode/size/mtime 与 SHA256 复核。变化将明确标记，不会自动覆盖基线。'
              : '请先完成文件索引，再明确选择一个或多个状态为 available 的索引根目录。'}</p>
            <fieldset className="nfc-v2-media-root-options" disabled={busy}>
              <legend>选择已索引根目录（至少一个）</legend>
              {options.length ? options.map(option => (
                <label key={option.value} title={option.disabled ? '该根目录不可用，不能加入队列' : undefined}>
                  <input type="checkbox" checked={roots.includes(option.value)}
                    disabled={option.disabled}
                    onChange={event => onChange(event.target.checked
                      ? [...roots, option.value]
                      : roots.filter(value => value !== option.value))} />
                  <span>{option.label}</span>
                </label>
              )) : <p>没有可用的索引根目录；请先完成文件索引。</p>}
            </fieldset>
          </div>
          <div className="nfc-v2-confirm-actions">
            <ConsoleButton disabled={busy} onClick={onClose}>取消</ConsoleButton>
            <ConsoleButton variant="primary" loading={busy}
              disabled={busy || roots.length === 0 || roots.some(root =>
                !options.some(option => option.value === root && !option.disabled))}
              onClick={onConfirm}>
              {isVerify ? '加入校验队列' : '加入分析队列'}
            </ConsoleButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};

interface DeleteSnapshot { ids: number[]; preview: CorruptDeletePreview; selectionVersion: number; }
const equalIds = (a: readonly number[], b: readonly number[]) =>
  a.length === b.length && [...a].sort((x, y) => x - y).every((value, i) =>
    value === [...b].sort((x, y) => x - y)[i]);

export const MediaPage: React.FC = () => {
  useTitle('媒体完整性');
  const { user } = useAuth();
  const toast = useConsoleToast();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === 'admin';

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [rootKey, setRootKey] = useState<string | undefined>();
  const [mediaKind, setMediaKind] = useState<'image' | 'video' | undefined>();
  const [integrityStatus, setIntegrityStatus] = useState<'healthy' | 'corrupt' | 'unknown' | undefined>();
  const [verificationStatus, setVerificationStatus] = useState<'unverified' | 'baseline' | 'verified' | 'changed' | 'unknown' | undefined>();
  const [search, setSearch] = useState('');
  const [searchApplied, setSearchApplied] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzeRoots, setAnalyzeRoots] = useState<string[]>([]);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [verifyRoots, setVerifyRoots] = useState<string[]>([]);
  const [deleteSnapshot, setDeleteSnapshot] = useState<DeleteSnapshot | null>(null);
  const [deletePreviewBusy, setDeletePreviewBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const selectionVersion = useRef(0);
  const previewInFlight = useRef(false);
  const deleteInFlight = useRef(false);
  const queueInFlight = useRef(false);

  const summaryQuery = useQuery({ queryKey: ['mediaSummary'], queryFn: mediaApi.summary });
  const mediaQuery = useQuery({
    queryKey: ['mediaList', page, pageSize, rootKey, mediaKind, integrityStatus, verificationStatus, searchApplied],
    queryFn: () => mediaApi.list({ page, pageSize, rootKey, mediaKind, integrityStatus, verificationStatus,
      search: searchApplied || undefined }),
  });
  const indexesQuery = useQuery({
    queryKey: ['indexesForMedia'], queryFn: () => indexesApi.listIndexes(1, 500),
  });

  const analyzeMutation = useMutation({
    mutationFn: (roots: string[]) => mediaApi.analyze(roots),
    onSuccess: result => {
      toast.success('媒体分析任务 #' + result.work_job_id + ' 已加入后台队列');
      setAnalyzeOpen(false); setAnalyzeRoots([]);
      void queryClient.invalidateQueries({ queryKey: ['mediaSummary'] });
      void queryClient.invalidateQueries({ queryKey: ['mediaList'] });
    },
    onError: (error: unknown) => toast.error(getStructuredApiError(error).message || '媒体分析任务创建失败'),
  });
  const verifyMutation = useMutation({
    mutationFn: (roots: string[]) => mediaApi.verifyIntegrity(roots),
    onSuccess: result => {
      toast.success('SHA256 完整性任务 #' + result.work_job_id + ' 已加入后台队列');
      setVerifyOpen(false); setVerifyRoots([]);
      void queryClient.invalidateQueries({ queryKey: ['mediaSummary'] });
      void queryClient.invalidateQueries({ queryKey: ['mediaList'] });
    },
    onError: (error: unknown) => toast.error(getStructuredApiError(error).message || 'SHA256 完整性任务创建失败'),
  });

  const rootOptions: RootOption[] = useMemo(() =>
    (indexesQuery.data?.items || []).map(root => ({
      value: root.root, label: root.root, disabled: root.path_state !== 'available',
    })), [indexesQuery.data?.items]);

  const availableRoots = (ids: string[]) =>
    ids.length > 0 && ids.every(id => rootOptions.some(root => root.value === id && !root.disabled));
  const handleQueue = async (kind: 'analyze' | 'verify') => {
    if (queueInFlight.current) return;
    const ids = kind === 'analyze' ? analyzeRoots : verifyRoots;
    const mutation = kind === 'analyze' ? analyzeMutation : verifyMutation;
    if (!availableRoots(ids)) { toast.error('请选择至少一个当前可用的已索引根目录'); return; }
    queueInFlight.current = true;
    try { await mutation.mutateAsync([...ids]); }
    catch { /* Toast was handled by mutation.onError; retain dialog for retry. */ }
    finally { queueInFlight.current = false; }
  };

  const rows = mediaQuery.data?.items || [];
  const canSelect = (record: MediaAsset) =>
    Boolean(isAdmin && record.integrity_status === 'corrupt' && record.can_direct_delete);
  const pageEligibleIds = rows.filter(canSelect).map(record => record.id);
  const pageAllSelected = pageEligibleIds.length > 0 && pageEligibleIds.every(id => selectedIds.includes(id));
  const resetSelection = () => {
    selectionVersion.current += 1;
    setSelectedIds([]);
    setDeleteSnapshot(null);
  };
  const updateSelection = (ids: number[]) => {
    if (deleteBusy || previewInFlight.current) return;
    selectionVersion.current += 1;
    setSelectedIds(ids);
    setDeleteSnapshot(null);
  };
  const toggleRow = (record: MediaAsset, checked: boolean) => {
    if (!canSelect(record)) return;
    updateSelection(checked ? [...selectedIds, record.id] : selectedIds.filter(id => id !== record.id));
  };
  const togglePage = (checked: boolean) => {
    updateSelection(checked ? [...new Set([...selectedIds, ...pageEligibleIds])] :
      selectedIds.filter(id => !pageEligibleIds.includes(id)));
  };
  const changePage = (nextPage: number, nextSize: number) => {
    if (deleteBusy) return;
    setPage(nextSize === pageSize ? nextPage : 1);
    setPageSize(nextSize);
    resetSelection();
  };
  const applySearch = () => {
    if (deleteBusy) return;
    setSearchApplied(search.trim()); setPage(1); resetSelection();
  };
  const changeFilter = (change: () => void) => {
    if (deleteBusy) return;
    change(); setPage(1); resetSelection();
  };

  const beginDeletePreview = async (ids: number[]) => {
    if (!isAdmin || deleteInFlight.current || previewInFlight.current || deleteBusy) return;
    const uniqueIds = [...new Set(ids)];
    if (!uniqueIds.length || uniqueIds.some(id => !rows.some(row => row.id === id && canSelect(row)))) {
      toast.error('只能选择当前列表中证据有效的 corrupt 文件；请重新筛选并选择');
      return;
    }
    const version = selectionVersion.current;
    previewInFlight.current = true; setDeletePreviewBusy(true);
    setDeleteSnapshot(null);
    try {
      const preview = await mediaApi.previewCorruptDelete(uniqueIds);
      if (selectionVersion.current !== version || !isAdmin) return;
      if (!equalIds(preview.selected_media_asset_ids, uniqueIds) || !preview.preview_digest ||
          preview.items.length !== uniqueIds.length ||
          !equalIds(preview.items.map(item => item.media_asset_id), uniqueIds)) {
        toast.error('Preview 与明确选择的媒体 ID 不一致，请重新选择并预览');
        return;
      }
      if (preview.blocked_count > 0 || preview.eligible_count !== uniqueIds.length ||
          preview.items.some(item => !item.eligible)) {
        const details = preview.items.filter(item => !item.eligible).slice(0, 5)
          .map(item => '#' + item.media_asset_id + ': ' + item.blockers.join(', ')).join('\n');
        toast.error('有 ' + preview.blocked_count + ' 个条目已不再满足永久删除条件\n' + details);
        return;
      }
      setDeleteSnapshot({ ids: uniqueIds, preview, selectionVersion: version });
    } catch (error: unknown) {
      if (selectionVersion.current === version) {
        toast.error(getStructuredApiError(error).message || '损坏媒体永久删除 Preview 失败');
      }
    } finally { previewInFlight.current = false; setDeletePreviewBusy(false); }
  };

  const deleteMutation = useMutation({
    mutationFn: async (snapshot: DeleteSnapshot) => {
      // The server revalidates identity, SHA256 and the frozen digest at every phase.
      const created = await mediaApi.createCorruptDeletePlan(snapshot.ids, snapshot.preview.preview_digest);
      await plansApi.freezePlan(created.id);
      const validated = await plansApi.validatePlan(created.id);
      if (validated.status !== 'ready') {
        throw new Error('永久删除计划校验未通过：' + validated.status);
      }
      const queued = await plansApi.executePlan(created.id);
      return { planId: created.id, workJobId: queued.work_job_id };
    },
    onSuccess: ({ planId, workJobId }) => {
      toast.success('永久删除计划 #' + planId + ' 已校验并加入 Worker 队列（任务 #' + workJobId + '）');
      resetSelection();
      void queryClient.invalidateQueries({ queryKey: ['mediaList'] });
      void queryClient.invalidateQueries({ queryKey: ['mediaSummary'] });
    },
    onError: (error: unknown) =>
      toast.error(getStructuredApiError(error).message || '创建损坏媒体永久删除计划失败'),
  });
  const handleConfirmedDelete = async () => {
    const snapshot = deleteSnapshot;
    if (!isAdmin || !snapshot || deleteInFlight.current || deleteBusy ||
        selectionVersion.current !== snapshot.selectionVersion) return;
    if (!snapshot.preview.preview_digest || snapshot.preview.blocked_count !== 0 ||
        snapshot.preview.eligible_count !== snapshot.ids.length) return;
    deleteInFlight.current = true; setDeleteBusy(true);
    try { await deleteMutation.mutateAsync(snapshot); }
    catch {
      // A partial Plan may exist. Re-preview and explicitly reconfirm before any retry.
      setDeleteSnapshot(null);
    } finally { deleteInFlight.current = false; setDeleteBusy(false); }
  };
  const closeDelete = (next: boolean) => {
    if (!next && !deleteInFlight.current && !deleteBusy) setDeleteSnapshot(null);
  };

  const renderPath = (record: MediaAsset) => (
    <div className="nfc-v2-media-file">
      <ConsoleIcon name={record.media_kind === 'image' ? 'file-search' : 'file-check'} size={18} />
      <div><CodePath value={record.path} /><span>{formatBytes(record.size)}</span></div>
    </div>
  );
  const rowCheckbox = (record: MediaAsset) => (
    <input type="checkbox" className="nfc-v2-media-checkbox"
      aria-label={'选择可永久删除损坏媒体 #' + record.id}
      checked={canSelect(record) && selectedIds.includes(record.id)}
      disabled={!canSelect(record) || deletePreviewBusy || deleteBusy}
      title={canSelect(record) ? '允许预览此 corrupt 条目的直接删除' : '只有证据有效的 corrupt 文件可永久删除'}
      onChange={event => toggleRow(record, event.target.checked)} />
  );
  const summary = summaryQuery.data;

  return (
    <div className="nfc-operations-page nfc-media-page nfc-page-layout-ledger nfc-v2-media-page">
      <PageHeader eyebrow="Media metadata + integrity" title="媒体完整性"
        description="独立分析图片/视频元数据，并建立 SHA256 基线复核内容变化；媒体探测与哈希校验不会修改源文件。"
        actions={<ActionBar compact>
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            loading={mediaQuery.isFetching || summaryQuery.isFetching}
            onClick={() => { void mediaQuery.refetch(); void summaryQuery.refetch(); }}>刷新</ConsoleButton>
          <ConsoleButton leadingIcon={<ConsoleIcon name="shield-check" size={16} />}
            onClick={() => setVerifyOpen(true)}>SHA256 校验</ConsoleButton>
          <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="play" size={16} />}
            onClick={() => setAnalyzeOpen(true)}>分析媒体</ConsoleButton>
        </ActionBar>}
      />

      <div className="nfc-metric-grid">
        <MetricCard label="已分析" value={(summary?.total ?? 0).toLocaleString()} meta="当前媒体结果" />
        <MetricCard label="正常" value={(summary?.healthy ?? 0).toLocaleString()} tone="success"
          icon={<ConsoleIcon name="check-circle" size={18} />} />
        <MetricCard label="损坏" value={(summary?.corrupt ?? 0).toLocaleString()} tone="danger"
          icon={<ConsoleIcon name="shield-check" size={18} />} />
        <MetricCard label="未知" value={(summary?.unknown ?? 0).toLocaleString()} tone="attention"
          icon={<ConsoleIcon name="info" size={18} />} />
        <MetricCard label="SHA256 变化" value={(summary?.verification_changed ?? 0).toLocaleString()}
          tone="danger" icon={<ConsoleIcon name="file-check" size={18} />} />
      </div>

      <DataPanel title="媒体目录"
        description="图片/视频 metadata 与完整性结果；unknown 不会被当作 corrupt。"
        variant="dense" className="nfc-panel-flush"
        action={<span className="nfc-panel-count">{mediaQuery.data?.total ?? 0} assets</span>}>
        <div className="nfc-filter-bar nfc-v2-media-filters">
          <label>索引根目录
            <select value={rootKey || ''} disabled={deleteBusy}
              onChange={event => changeFilter(() => setRootKey(event.target.value || undefined))}>
              <option value="">全部根目录</option>
              {rootOptions.map(option => <option key={option.value} value={option.value}
                disabled={option.disabled}>{option.label}</option>)}
            </select>
          </label>
          <label>媒体类型
            <select value={mediaKind || ''} disabled={deleteBusy}
              onChange={event => changeFilter(() =>
                setMediaKind((event.target.value || undefined) as typeof mediaKind))}>
              <option value="">全部类型</option><option value="image">图片</option><option value="video">视频</option>
            </select>
          </label>
          <label>完整性
            <select value={integrityStatus || ''} disabled={deleteBusy}
              onChange={event => changeFilter(() =>
                setIntegrityStatus((event.target.value || undefined) as typeof integrityStatus))}>
              <option value="">全部状态</option><option value="healthy">正常</option>
              <option value="corrupt">损坏</option><option value="unknown">未知</option>
            </select>
          </label>
          <label>SHA256 校验
            <select value={verificationStatus || ''} disabled={deleteBusy}
              onChange={event => changeFilter(() =>
                setVerificationStatus((event.target.value || undefined) as typeof verificationStatus))}>
              <option value="">全部状态</option><option value="unverified">未建立</option>
              <option value="baseline">基线已建立</option><option value="verified">校验通过</option>
              <option value="changed">内容变化</option><option value="unknown">无法校验</option>
            </select>
          </label>
          <form className="nfc-v2-media-search" onSubmit={event => { event.preventDefault(); applySearch(); }}>
            <label htmlFor="media-search-input">搜索路径
              <input id="media-search-input" type="search" value={search}
                disabled={deleteBusy} placeholder="搜索文件名或路径"
                onChange={event => setSearch(event.target.value)} />
            </label>
            <ConsoleButton type="submit" size="sm">搜索</ConsoleButton>
          </form>
          <ConsoleButton variant="danger" size="sm" className="nfc-media-destructive-action"
            leadingIcon={<ConsoleIcon name="trash" size={15} />}
            disabled={!isAdmin || selectedIds.length === 0 || deleteBusy || deletePreviewBusy}
            loading={deletePreviewBusy}
            onClick={() => { void beginDeletePreview(selectedIds); }}>
            永久删除损坏文件 ({selectedIds.length})
          </ConsoleButton>
        </div>
        <div className="nfc-v2-media-warning" role="alert">
          <ConsoleIcon name="shield-check" size={18} />
          <span><strong>永久删除会绕过文件隔离区。</strong>
            仅 corrupt + frozen SHA256 证据有效的条目可选；执行前再次校验路径、
            dev/inode/size/mtime 与 SHA256。healthy / unknown 永远不会进入此删除动作。</span>
        </div>
        {mediaQuery.isError && <div className="nfc-v2-media-loading" role="alert">
          媒体列表读取失败：{getStructuredApiError(mediaQuery.error).message}
          <ConsoleButton size="sm" onClick={() => { void mediaQuery.refetch(); }}>重试</ConsoleButton>
        </div>}
        {!mediaQuery.isError && mediaQuery.isLoading &&
          <div className="nfc-v2-media-loading" role="status">正在读取媒体结果…</div>}
        {!mediaQuery.isError && !mediaQuery.isLoading && !rows.length &&
          <ConsoleEmpty title="暂无媒体分析结果" description="调整筛选或在上方启动媒体分析。" />}
        {!mediaQuery.isError && !mediaQuery.isLoading && rows.length > 0 && (
          <>
            <ResponsiveDataView
              desktop={<div className="nfc-v2-media-table-scroll">
                <table className="nfc-v2-media-table">
                  <thead><tr>
                    <th scope="col"><input type="checkbox" className="nfc-v2-media-checkbox"
                      checked={pageAllSelected} disabled={!isAdmin || pageEligibleIds.length === 0 || deleteBusy || deletePreviewBusy}
                      aria-label="选择本页可永久删除的损坏媒体"
                      onChange={event => togglePage(event.target.checked)} /></th>
                    <th scope="col">媒体文件</th><th scope="col">完整性</th>
                    <th scope="col">SHA256 校验</th><th scope="col">尺寸 / 时长</th>
                    <th scope="col">格式 / 编码</th><th scope="col">拍摄 / 探测</th>
                    <th scope="col">删除资格</th>
                  </tr></thead>
                  <tbody>{rows.map(record => (
                    <tr key={record.id}>
                      <td>{rowCheckbox(record)}</td>
                      <td>{renderPath(record)}</td>
                      <td>{integrityBadge(record)}</td>
                      <td>{verificationBadge(record)}</td>
                      <td className="nfc-table-meta">
                        {record.width && record.height ? record.width + '×' + record.height : '—'}
                        {record.media_kind === 'video' ? ' · ' + formatDuration(record.duration_seconds) : ''}
                      </td>
                      <td className="nfc-table-meta">{record.media_kind === 'image'
                        ? record.format || 'unknown'
                        : [record.format, record.codec, record.audio_codec].filter(Boolean).join(' / ') || 'unknown'}</td>
                      <td className="nfc-table-meta">
                        {record.date_taken || record.camera || '—'}
                        <small>{record.probed_at ? formatDateTime(record.probed_at) : '—'}</small>
                      </td>
                      <td>{record.can_direct_delete && record.integrity_status === 'corrupt'
                        ? <span className="nfc-v2-media-status is-corrupt">可永久删除</span>
                        : <span className="nfc-table-muted">—</span>}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<div className="nfc-mobile-record-list nfc-v2-media-mobile">
                {rows.map(record => (
                  <article className="nfc-index-mobile-card" key={record.id}>
                    <div className="nfc-mobile-record-heading">
                      {renderPath(record)}
                      <div className="nfc-v2-media-badges">{integrityBadge(record)}{verificationBadge(record)}</div>
                    </div>
                    <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                      <span>大小 <b>{formatBytes(record.size)}</b></span>
                      <span>尺寸 <b>{record.width && record.height ? record.width + '×' + record.height : '—'}</b></span>
                      <span>格式 <b>{record.format || record.codec || 'unknown'}</b></span>
                    </div>
                    {record.integrity_reason_code &&
                      <div className="nfc-mobile-record-note">{record.integrity_reason_code}</div>}
                    <div className="nfc-mobile-record-actions">
                      {rowCheckbox(record)}
                      <ConsoleButton size="sm" variant="danger"
                        disabled={!canSelect(record) || deleteBusy || deletePreviewBusy}
                        onClick={() => { void beginDeletePreview([record.id]); }}>
                        永久删除
                      </ConsoleButton>
                    </div>
                  </article>
                ))}
              </div>}
            />
            <ConsolePagination page={page} pageSize={pageSize}
              total={mediaQuery.data?.total || 0} pageSizes={[20, 50, 100, 200]}
              onChange={changePage} />
          </>
        )}
      </DataPanel>

      <QueueDialog kind="analyze" open={analyzeOpen} roots={analyzeRoots}
        options={rootOptions} busy={analyzeMutation.isPending}
        onClose={() => { if (!queueInFlight.current) { setAnalyzeOpen(false); setAnalyzeRoots([]); } }}
        onChange={setAnalyzeRoots} onConfirm={() => { void handleQueue('analyze'); }} />
      <QueueDialog kind="verify" open={verifyOpen} roots={verifyRoots}
        options={rootOptions} busy={verifyMutation.isPending}
        onClose={() => { if (!queueInFlight.current) { setVerifyOpen(false); setVerifyRoots([]); } }}
        onChange={setVerifyRoots} onConfirm={() => { void handleQueue('verify'); }} />

      <ConsoleConfirmDialog open={deleteSnapshot !== null} onOpenChange={closeDelete}
        title={'永久删除 ' + (deleteSnapshot?.preview.eligible_count || 0) + ' 个损坏媒体文件？'}
        description={<div className="nfc-confirm-copy">
          <p><strong>该操作不会移动到文件隔离区。原文件将直接 unlink，应用内无法恢复。</strong></p>
          <p>服务端 Preview 认定 {deleteSnapshot?.preview.eligible_count || 0} 个可操作条目，
            预计释放 {formatBytes(deleteSnapshot?.preview.total_bytes || 0)}。</p>
          <p>执行前仍会重新校验路径、dev/inode、size、mtime 与 SHA256；任何变化都会 fail-closed。</p>
          <p>预览摘要：<code>{deleteSnapshot?.preview.preview_digest.slice(0, 20)}…</code></p>
        </div>}
        confirmText="永久删除并提交 Worker" busy={deleteBusy}
        disabled={!isAdmin || !deleteSnapshot ||
          selectionVersion.current !== deleteSnapshot.selectionVersion ||
          deleteSnapshot.preview.blocked_count > 0}
        onConfirm={() => { void handleConfirmedDelete(); }} />
    </div>
  );
};
