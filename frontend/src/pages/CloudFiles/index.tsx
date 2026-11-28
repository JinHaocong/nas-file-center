import { useLayoutEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { DataPanel } from '../../components/ui/DataPanel';
import { PageHeader } from '../../components/ui/PageHeader';

import { cloudFilesApi, type CloudCopySubmission, type CloudFileProvider, type CloudFilesConfiguration } from '../../api/cloudFiles';

import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { CloudBrowser } from './CloudBrowser';
import { cloudTransfersKey, TransferLedger, useCloudTransferList, type RecentTransfer } from './TransferLedger';
import { isLiveTransfer, providerLabel } from './presentation';

const providers = ['openlist', 'rclone'] as const;
const nativeDiscoveryWindow = 20_000;

/** Present selection and the native task ledger in the same independent workspace. */
function CloudWorkspace({ configuration }: { configuration: CloudFilesConfiguration }) {
  const queries = useQueryClient();
  const toast = useConsoleToast();
  const [selectedProvider, setSelectedProvider] = useState<CloudFileProvider | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentTransfer[]>([]);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [keepTransfersOpen, setKeepTransfersOpen] = useState(false);
  const [dismissedTransfers, setDismissedTransfers] = useState<ReadonlySet<string>>(new Set());
  const transferTrigger = useRef<HTMLButtonElement>(null);
  const revealOnMobile = useRef(false);
  const activity = useCloudTransferList(configuration.enabled, recent);
  const liveIds = activity.transfers.filter(transfer => isLiveTransfer(transfer.status)).map(transfer => transfer.id);
  const historyCount = activity.transfers.length - liveIds.length;
  const transferWarning = activity.list.isError || Object.values(activity.list.data?.errors || {}).some(Boolean);
  const transfersOpen = keepTransfersOpen || openId !== null || liveIds.some(id => !dismissedTransfers.has(id));
  const provider = selectedProvider && configuration[selectedProvider].enabled
    ? selectedProvider : providers.find(item => configuration[item].enabled);
  const service = provider ? configuration[provider] : undefined;

  useLayoutEffect(() => {
    if (!transfersOpen || !revealOnMobile.current) return;
    revealOnMobile.current = false;
    const pane = document.getElementById('nfc-cloud-files-transfers');
    pane?.scrollIntoView({ block: 'start' });
    pane?.querySelector<HTMLElement>('.nfc-cloud-transfer-scroll')?.focus({ preventScroll: true });
  }, [transfersOpen]);

  /** Fold explicitly and restore the toolbar entry, preserving a newly discovered task's ability to reveal the pane. */
  function collapseTransfers() {
    setOpenId(null);
    setKeepTransfersOpen(false);
    setDismissedTransfers(new Set(liveIds));
    transferTrigger.current?.focus({ preventScroll: !window.matchMedia('(max-width: 860px)').matches });
  }

  /** Show a new receipt immediately while the native state is polled independently. */
  function openReceipt(receipt: CloudCopySubmission) {
    if (!('id' in receipt)) {
      setSubmissionError(null);
      return;
    }
    setSubmissionError(receipt.error);
    if (!receipt.error) toast.success('复制任务已提交');
    queries.setQueryData([...cloudTransfersKey, receipt.id], receipt);
    const now = Date.now();
    setRecent(current => [{ receipt, expires: now + nativeDiscoveryWindow },
      ...current.filter(item => item.receipt.id !== receipt.id && item.expires > now)].slice(0, 30));
    setOpenId(receipt.id);
    void queries.invalidateQueries({ queryKey: cloudTransfersKey });
  }

  return (
    <div className="nfc-cloud-files-layout" data-transfers-open={transfersOpen ? 'true' : undefined}>
      <div className="nfc-cloud-files-sources">
        <div className="nfc-cloud-provider-switch">
          <div className="nfc-cloud-provider-control" role="group" aria-label="云端来源" data-provider={provider}>
            {providers.map(item => (
              <ConsoleButton key={item} size="sm" variant="ghost" disabled={!configuration[item].enabled}
                aria-pressed={provider === item} onClick={() => setSelectedProvider(item)}>{providerLabel[item]}</ConsoleButton>
            ))}
          </div>
          <ConsoleButton ref={transferTrigger} size="sm" variant="ghost" className="nfc-cloud-transfer-trigger"
            aria-label="传输任务" aria-expanded={transfersOpen} aria-describedby="nfc-cloud-transfer-summary"
            aria-controls={transfersOpen ? 'nfc-cloud-files-transfers' : undefined}
            leadingIcon={<ConsoleIcon name="activity" size={16} />}
            onClick={() => {
              if (transfersOpen) {
                collapseTransfers();
                return;
              }
              revealOnMobile.current = window.matchMedia('(max-width: 860px)').matches;
              setKeepTransfersOpen(true);
            }}>
            <span>传输任务</span>
            <span className="nfc-cloud-transfer-trigger-count" id="nfc-cloud-transfer-summary">
              {liveIds.length > 0 ? liveIds.length + ' 个进行中' : historyCount > 0
                ? historyCount + ' 条记录' : activity.list.isPending ? '读取中' : '无任务'}
              {transferWarning && <span className="nfc-cloud-transfer-trigger-warning"> · 读取异常</span>}
            </span>
          </ConsoleButton>
        </div>
        {submissionError && <p className="nfc-cloud-files-error" role="alert">{submissionError}</p>}
        {provider && service && configuration.local_root && configuration.enabled ? (
          <CloudBrowser key={provider + '/' + configuration.local_root} provider={provider}
            name={service.name || providerLabel[provider]} localRoot={configuration.local_root}
            writable={configuration.writable} onSubmitted={openReceipt} />
        ) : <DataPanel title="云端目录"><ConsoleEmpty title="云端复制尚未配置"
          description="为此部署配置 OpenList 或 rclone，以及允许写入的 NAS 目录。" /></DataPanel>}
      </div>
      {transfersOpen && <TransferLedger configuration={configuration} activity={activity}
        openId={openId} onOpen={setOpenId} onInteract={() => setKeepTransfersOpen(true)} onCollapse={collapseTransfers}
        onDismissReceipt={id => setRecent(current => current.filter(item => item.receipt.id !== id))} />}
    </div>
  );
}

/** Serve the cloud workspace and keep provider connections behind the admin session. */
export function CloudFilesPage() {
  useTitle('云端文件');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const config = useQuery({
    queryKey: ['cloud-files', 'configuration'], queryFn: cloudFilesApi.configuration,
    retry: false, enabled: isAdmin,
  });

  return (
    <div className="nfc-operations-page nfc-page-layout-workbench nfc-tool-workspace nfc-cloud-files-page">
      <PageHeader className="nfc-cloud-files-header" title="云端文件"
        actions={isAdmin && <Link className="nfc-console-button nfc-console-button-ghost nfc-console-button-sm"
          to="/download-sources"><ConsoleIcon name="settings" size={15} />管理 OpenList 来源</Link>} />
      {!isAdmin && <DataPanel title="云端访问"><ConsoleEmpty title="仅管理员可以管理云端文件和传输。" /></DataPanel>}
      {isAdmin && config.isPending && <p className="nfc-cloud-files-muted" role="status">正在读取云端配置…</p>}
      {isAdmin && config.isError && <div className="nfc-cloud-files-failure" role="alert">
        <span>无法读取云端配置。</span>
        <ConsoleButton size="sm" onClick={() => { void config.refetch(); }}>重试</ConsoleButton>
      </div>}
      {isAdmin && config.data && <CloudWorkspace configuration={config.data} />}
    </div>
  );
}
