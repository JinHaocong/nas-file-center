import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ProgressMotionTrack } from '../../components/ui/ProgressMotionTrack';
import { StatusBadge } from '../../components/ui/StatusBadge';

import { cloudFilesApi, type CloudFileProvider, type CloudFilesConfiguration, type CloudTransfer,
  type CloudTransferFile, type CloudTransfers } from '../../api/cloudFiles';
import { getStructuredApiError } from '../../api/errors';

import { formatDateTime } from '../../utils/format';
import { describeCloudFile, displayBytes, displaySpeed, estimateOpenListSpeed, isLiveTransfer,
  nativeTransferPage, providerLabel, statusLabel, verificationPage } from './presentation';

export const cloudTransfersKey = ['cloud-files', 'transfers'] as const;
const pollInterval = 3000;
const discoveryInterval = 10_000;
const filePageSize = 30;
const emptyTransfers: CloudTransfer[] = [];

interface PendingAction {
  kind: 'cancel' | 'delete';
  id: string;
}

export interface RecentTransfer {
  receipt: CloudTransfer;
  expires: number;
}

interface Props {
  configuration: CloudFilesConfiguration;
  openId: string | null;
  onOpen: (id: string | null) => void;
  focusRequest: { id: string | null } | null;
  activity: ReturnType<typeof useCloudTransferList>;
  onInteract: () => void;
  onCollapse: () => void;
  onDismissReceipt: (id: string) => void;
}

/** Keep the last OpenList observation in memory for the currently expanded task only. */
function useObservedTransfer(transfer: CloudTransfer | undefined, observedAt: number): CloudTransfer | undefined {
  const previous = useRef<{ transfer: CloudTransfer; at: number } | null>(null);
  const [estimate, setEstimate] = useState<{ base: CloudTransfer; at: number; value: CloudTransfer } | null>(null);
  useEffect(() => {
    if (!transfer || transfer.provider !== 'openlist') {
      previous.current = null;
      return;
    }
    const older = previous.current;
    if (older?.at === observedAt && older.transfer.id === transfer.id) return;
    previous.current = { transfer, at: observedAt };
    if (older && older.transfer.id === transfer.id) {
      setEstimate({ base: transfer, at: observedAt, value: estimateOpenListSpeed(older.transfer, transfer, observedAt - older.at) });
    }
  }, [observedAt, transfer]);
  return estimate && estimate.base === transfer && estimate.at === observedAt ? estimate.value : transfer;
}

/** Measure visible OpenList transfers from two list responses without keeping task history. */
function useObservedList(transfers: CloudTransfer[], observedAt: number): CloudTransfer[] {
  const sample = useRef<{ items: CloudTransfer[]; at: number } | null>(null);
  const [measurement, setMeasurement] = useState<{ base: CloudTransfer[]; at: number; values: CloudTransfer[] } | null>(null);
  useEffect(() => {
    const previous = sample.current;
    if (previous?.at === observedAt) return;
    sample.current = { items: transfers, at: observedAt };
    if (!previous) return;
    const byId = new Map(previous.items.map(transfer => [transfer.id, transfer]));
    const values = transfers.map(transfer => {
      const older = byId.get(transfer.id);
      return older ? estimateOpenListSpeed(older, transfer, observedAt - previous.at) : transfer;
    });
    setMeasurement({ base: transfers, at: observedAt, values });
  }, [observedAt, transfers]);
  return measurement && measurement.base === transfers && measurement.at === observedAt ? measurement.values : transfers;
}

/** Use names when there is one item and a concise summary for multi-select copies. */
function transferName(transfer: CloudTransfer): string {
  return transfer.names.length > 1 ? transfer.names[0] + ' 等 ' + transfer.names.length + ' 项'
    : transfer.names[0] || '云端复制';
}

/** Ignore unavailable or invalid percentages instead of inventing a denominator. */
function displayPercent(value: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100
    ? Math.round(value) : null;
}

/** Render actual progress and keep unknown progress explicit. */
function TransferProgress({ value, label }: { value: number | null; label: string }) {
  return value === null
    ? <span className="nfc-cloud-files-muted">进度待确认</span>
    : <div className="nfc-cloud-transfer-progress">
      <ProgressMotionTrack value={value}>
        <progress className="nfc-v2-native-progress" max={100} value={value} aria-label={label} />
      </ProgressMotionTrack>
    </div>;
}

/** Keep the filename and its parent readable when a transfer spans several levels. */
function TransferFileRow({ file }: { file: CloudTransferFile }) {
  const slash = file.name.lastIndexOf('/');
  const name = file.name.slice(slash + 1);
  const percent = displayPercent(file.progress);
  const normal = file.status === 'running' || file.status === 'completed';
  return <li>
    <div className="nfc-cloud-transfer-file-heading">
      <div className="nfc-cloud-transfer-file-name">
        <ConsoleIcon name={describeCloudFile(name).icon} size={14} />
        <div>
          <strong>{name}</strong>
          {slash > 0 && <small>{file.name.slice(0, slash)}</small>}
        </div>
      </div>
      {normal && percent !== null ? <span className="nfc-cloud-file-percent">{percent}%</span>
        : <StatusBadge status={file.status} label={statusLabel[file.status]} />}
    </div>
    <TransferProgress value={percent} label={file.name + '复制进度'} />
    <div className="nfc-cloud-transfer-file-metrics">
      <span>{displayBytes(file.bytes)} / {displayBytes(file.total_bytes)}</span>
      {file.speed !== null && <span className="nfc-cloud-transfer-file-speed">{displaySpeed(file.speed, file.speed_estimated)}</span>}
    </div>
  </li>;
}

/** Native task output remains available under its original service and task ids. */
function TransferDetails({ transfer, configuration }: { transfer: CloudTransfer; configuration: CloudFilesConfiguration }) {
  const [page, setPage] = useState(1);
  const webUrl = nativeTransferPage(transfer.provider, configuration[transfer.provider].web_url);
  return <div className="nfc-cloud-transfer-details">
    {transfer.files.length === 0
      ? <p className="nfc-cloud-files-muted">服务暂未提供单文件进度。</p>
      : <>
        <h3 className="nfc-cloud-files-measure-title">逐文件进度</h3>
        <ul className="nfc-cloud-transfer-files" aria-label="逐文件进度">
          {transfer.files.slice(0, page * filePageSize).map((file, index) =>
            <TransferFileRow key={file.name + '/' + index} file={file} />)}
        </ul>
        {transfer.files.length > page * filePageSize &&
          <ConsoleButton variant="ghost" size="sm" onClick={() => setPage(count => count + 1)}>
            显示更多文件（{page * filePageSize} / {transfer.files.length}）
          </ConsoleButton>}
      </>}
    <details className="nfc-cloud-transfer-metadata">
      <summary>传输信息</summary>
      <dl className="nfc-cloud-transfer-fields">
        <div><dt>NAS 目标</dt><dd><CodePath value={transfer.destination} /></dd></div>
        <div><dt>原生任务编号</dt><dd>{transfer.native_ids.length ? transfer.native_ids.join('、') : '—'}</dd></div>
        <div><dt>创建时间</dt><dd>{formatDateTime(transfer.created_at)}</dd></div>
      </dl>
    </details>
    {(webUrl || (transfer.status === 'completed' && transfer.verification)) && (
      <div className="nfc-cloud-transfer-links">
        {webUrl && <a target="_blank" rel="noopener noreferrer" href={webUrl}>
          打开 {providerLabel[transfer.provider]} 传输页 <ConsoleIcon name="arrow-right" size={13} />
        </a>}
        {transfer.status === 'completed' && transfer.verification &&
          <Link to={verificationPage(transfer.verification)}>下载完整性校验</Link>}
      </div>
    )}
  </div>;
}

/** Keep discovery and provider observations active while the transfer pane is folded. */
export function useCloudTransferList(enabled: boolean, recent: RecentTransfer[]) {
  const list = useQuery({
    queryKey: cloudTransfersKey, queryFn: cloudFilesApi.list, retry: false,
    refetchInterval: query => recent.some(item => item.expires > Date.now()) ||
      query.state.data?.items.some(transfer => isLiveTransfer(transfer.status))
      ? pollInterval : enabled ? discoveryInterval : false,
  });
  const liveTransfers = useObservedList(list.data?.items || emptyTransfers, list.dataUpdatedAt);
  const listedIds = new Set(liveTransfers.map(transfer => transfer.id));
  const waiting = recent.filter(item => item.expires > Date.now() && !listedIds.has(item.receipt.id));
  const transfers = [...waiting.map(item => item.receipt), ...liveTransfers];
  return { list, waiting, transfers };
}

/** Show live transfer details and guard mutations against stale permissions. */
export function TransferLedger({ configuration, openId, onOpen, focusRequest, activity, onInteract,
  onCollapse, onDismissReceipt }: Props) {
  const client = useQueryClient();
  const idPrefix = useId();
  const [action, setAction] = useState<PendingAction | null>(null);
  const [error, setError] = useState('');
  const [visibleCount, setVisibleCount] = useState(filePageSize);
  const [refreshing, setRefreshing] = useState(false);
  const inFlight = useRef(false);
  const pane = useRef<HTMLElement>(null);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const { list, waiting, transfers } = activity;
  const openSummary = transfers.find(transfer => transfer.id === openId);
  const visible = transfers.slice(0, visibleCount);
  if (openSummary && !visible.includes(openSummary)) visible.push(openSummary);
  useLayoutEffect(() => {
    const region = scrollRegion.current;
    if (!region || !focusRequest) return;
    if (window.matchMedia('(max-width: 860px)').matches) pane.current?.scrollIntoView({ block: 'start' });
    const row = focusRequest.id && region.querySelector<HTMLElement>(`[data-transfer-id="${CSS.escape(focusRequest.id)}"]`);
    if (row) {
      const bounds = row.getBoundingClientRect();
      const viewport = region.getBoundingClientRect();
      if (bounds.top < viewport.top || bounds.bottom > viewport.bottom) region.scrollTop += bounds.top - viewport.top;
      row.focus({ preventScroll: true });
    } else {
      region.focus({ preventScroll: true });
    }
  }, [focusRequest]);
  const detail = useQuery({
    queryKey: [...cloudTransfersKey, openId], queryFn: () => cloudFilesApi.detail(openId!),
    enabled: openId !== null, retry: false,
    refetchInterval: query => isLiveTransfer(query.state.data?.status ?? openSummary?.status) ? pollInterval : false,
  });
  const observed = useObservedTransfer(detail.data, detail.dataUpdatedAt);
  const awaitingNative = waiting.some(item => item.receipt.id === openId) &&
    detail.isError && getStructuredApiError(detail.error).status === 404;
  const actionTransfer = detail.data?.id === action?.id
    ? detail.data : list.data?.items.find(transfer => transfer.id === action?.id);
  const canAct = action?.kind === 'cancel'
    ? actionTransfer?.can_cancel === true : actionTransfer?.can_delete === true;
  const mutate = useMutation({
    mutationFn: async (item: PendingAction) => {
      if (item.kind === 'cancel') {
        const receipt = await cloudFilesApi.cancel(item.id);
        client.setQueryData([...cloudTransfersKey, item.id], receipt);
        client.setQueryData<CloudTransfers>(cloudTransfersKey, old => old && { ...old,
          items: old.items.map(transfer => transfer.id === item.id ? receipt : transfer),
        });
        return;
      }
      await cloudFilesApi.remove(item.id);
      client.removeQueries({ queryKey: [...cloudTransfersKey, item.id], exact: true });
      client.setQueryData<CloudTransfers>(cloudTransfersKey, old => old && { ...old,
        items: old.items.filter(transfer => transfer.id !== item.id),
      });
      onDismissReceipt(item.id);
      if (openId === item.id) onOpen(null);
    },
  });

  /** Apply one confirmed action and reconcile with the provider-backed transfer list. */
  async function confirmAction() {
    if (!action || !canAct || inFlight.current) return;
    inFlight.current = true;
    setError('');
    try {
      await mutate.mutateAsync(action);
      setAction(null);
    } catch (failure) {
      setError(getStructuredApiError(failure).message || '无法修改任务状态，请重试。');
    } finally {
      inFlight.current = false;
      void client.invalidateQueries({ queryKey: cloudTransfersKey });
    }
  }

  /** Show a busy indicator for the refresh button's own request, independent of polling. */
  async function refreshTransfers() {
    setRefreshing(true);
    try {
      await client.invalidateQueries({ queryKey: cloudTransfersKey });
    } finally {
      setRefreshing(false);
    }
  }

  const liveCount = transfers.filter(transfer => isLiveTransfer(transfer.status)).length;
  const cancelling = action?.kind === 'cancel';
  const providerErrors = Object.entries(list.data?.errors || {}) as [CloudFileProvider, string][];
  return <section ref={pane} id="nfc-cloud-files-transfers" className="nfc-cloud-files-ledger" aria-labelledby="nfc-cloud-transfer-title"
    onFocusCapture={onInteract}>
    <header className="nfc-cloud-ledger-header">
      <div className="nfc-cloud-ledger-title">
        <ConsoleIcon name="activity" size={16} />
        <h2 id="nfc-cloud-transfer-title">传输任务</h2>
      </div>
      <div className="nfc-cloud-ledger-controls">
        {liveCount > 0 && <span className="nfc-cloud-ledger-count">{liveCount} 个进行中</span>}
        <ConsoleButton size="sm" variant="ghost" disabled={list.isFetching} loading={refreshing} aria-label="刷新传输任务"
          leadingIcon={<ConsoleIcon name="refresh" size={16} />}
          onClick={() => { void refreshTransfers(); }} />
        <ConsoleButton size="sm" variant="ghost" aria-label="折叠传输任务" onClick={onCollapse}
          leadingIcon={<ConsoleIcon name="x" size={16} />} />
      </div>
    </header>
    <div ref={scrollRegion} className="nfc-cloud-transfer-scroll" role="region" aria-label="传输任务列表" tabIndex={0}>
      {list.isPending && <p className="nfc-cloud-files-muted nfc-cloud-ledger-message" role="status">正在读取传输任务…</p>}
      {list.isError && <p className="nfc-cloud-files-error nfc-cloud-ledger-message" role="alert">无法刷新传输任务，请重试。</p>}
      {providerErrors.map(([provider, message]) => (
        <p key={provider} className="nfc-cloud-files-muted nfc-cloud-ledger-message" role="status">{providerLabel[provider]} · {message}</p>
      ))}
      {list.isSuccess && transfers.length === 0 && <p className="nfc-cloud-ledger-empty">
        <ConsoleIcon name="activity" size={17} />
        <span>{providerErrors.length ? '暂无可读取的任务' : '暂无传输任务'}</span>
      </p>}
      <ul className="nfc-cloud-transfer-list" aria-label="传输任务记录">
        {visible.map(transfer => {
          const expanded = transfer.id === openId;
          const updated = expanded && observed?.id === transfer.id ? observed : transfer;
          const title = transferName(updated);
          const detailId = idPrefix + '-' + transfer.id;
          const source = updated.remote ? providerLabel[updated.provider] + ' · ' + updated.remote : providerLabel[updated.provider];
          const native = updated.native_ids[0];
          const percent = displayPercent(updated.progress);
          return (
            <li className="nfc-cloud-transfer-row" key={transfer.id} data-transfer-id={transfer.id} tabIndex={-1}>
              <div className="nfc-cloud-transfer-heading">
                <div><strong title={native ? '原生任务 #' + native : undefined}>{title}</strong>
                  <span className="nfc-cloud-files-muted">{source}</span>
                </div>
                <StatusBadge status={updated.status} label={statusLabel[updated.status]} />
              </div>
              {(percent !== null || updated.speed !== null) && <div className="nfc-cloud-transfer-summary">
                {percent !== null && <span className="nfc-cloud-files-muted">{percent}%</span>}
                {updated.speed !== null && <span className="nfc-cloud-transfer-speed">
                  {displaySpeed(updated.speed, updated.speed_estimated)}
                </span>}
              </div>}
              <TransferProgress value={percent} label={title + '整笔复制进度'} />
              {updated.error && <p className="nfc-cloud-files-error">{updated.error}</p>}
              <div className="nfc-cloud-transfer-actions">
                <ConsoleButton size="sm" variant="ghost" aria-expanded={expanded} aria-controls={detailId}
                  leadingIcon={<ConsoleIcon className="nfc-cloud-transfer-chevron" name="chevron-right" size={14} />}
                  onClick={() => onOpen(expanded ? null : transfer.id)}>{expanded ? '收起详情' : '查看详情'}</ConsoleButton>
                {updated.can_cancel && <ConsoleButton size="sm" variant="ghost"
                  onClick={() => { setError(''); setAction({ kind: 'cancel', id: transfer.id }); }}>取消复制</ConsoleButton>}
                {updated.can_delete && <ConsoleButton size="sm" variant="ghost"
                  leadingIcon={<ConsoleIcon name="trash" size={14} />}
                  onClick={() => { setError(''); setAction({ kind: 'delete', id: transfer.id }); }}>删除记录</ConsoleButton>}
              </div>
              <div id={detailId} hidden={!expanded}>
                {expanded && <>
                  {detail.isPending && <p className="nfc-cloud-files-muted" role="status">正在取得单文件进度…</p>}
                  {awaitingNative && <p className="nfc-cloud-files-muted" role="status">已提交，正在等待原服务报告进度…</p>}
                  {detail.isError && !awaitingNative && <p className="nfc-cloud-files-error" role="alert">详情暂不可用。</p>}
                  {observed?.id === transfer.id && <TransferDetails key={transfer.id}
                    transfer={observed} configuration={configuration} />}
                </>}
              </div>
            </li>
          );
        })}
      </ul>
      {transfers.length > visibleCount && <div className="nfc-cloud-ledger-message">
        <ConsoleButton variant="ghost" size="sm" onClick={() => setVisibleCount(count => count + filePageSize)}>
          显示更多任务（{visibleCount} / {transfers.length}）
        </ConsoleButton>
      </div>}
    </div>
    <ConsoleConfirmDialog open={action !== null}
      onOpenChange={visible => { if (!visible) setAction(null); }}
      title={cancelling ? '取消复制任务' : '删除传输记录'}
      description={<>
        <p>{cancelling ? '向原服务提交停止请求，保留已写入 NAS 的文件。' : '清除这条原生传输的记录，保留已复制的 NAS 文件。'}</p>
        {error && <p className="nfc-cloud-files-error" role="alert">{error}</p>}
      </>}
      confirmText={cancelling ? '停止传输' : '删除记录'} busy={mutate.isPending} disabled={!canAct}
      onConfirm={() => { void confirmAction(); }} />
  </section>;
}
