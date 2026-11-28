import { useLayoutEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { DataPanel } from '../../components/ui/DataPanel';
import { PageHeader } from '../../components/ui/PageHeader';
import { CloudCopyNotice } from './CloudCopyNotice';

import { cloudFilesApi, type CloudCopySubmission, type CloudFileProvider, type CloudFilesConfiguration } from '../../api/cloudFiles';

import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { CloudBrowser } from './CloudBrowser';
import { cloudTransfersKey, TransferLedger, useCloudTransferList, type RecentTransfer } from './TransferLedger';
import { formatCloudSubmission, isLiveTransfer, providerLabel } from './presentation';

const providers = ['openlist', 'rclone'] as const;
const nativeDiscoveryWindow = 20_000;

/** Present selection and the native task ledger in the same independent workspace. */
function CloudWorkspace({ configuration }: { configuration: CloudFilesConfiguration }) {
  const queries = useQueryClient();
  const [selectedProvider, setSelectedProvider] = useState<CloudFileProvider | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentTransfer[]>([]);
  const [receipt, setReceipt] = useState<{ result: CloudCopySubmission; destination: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [keepTransfersOpen, setKeepTransfersOpen] = useState(false);
  const [dismissedTransfers, setDismissedTransfers] = useState<ReadonlySet<string>>(new Set());
  const transferTrigger = useRef<HTMLButtonElement>(null);
  const activeProviderTab = useRef<HTMLButtonElement>(null);
  const focusProvider = useRef(false);
  const [ledgerFocus, setLedgerFocus] = useState<{ id: string | null } | null>(null);
  const activity = useCloudTransferList(configuration.enabled, recent);
  const liveIds = activity.transfers.filter(transfer => isLiveTransfer(transfer.status)).map(transfer => transfer.id);
  const historyCount = activity.transfers.length - liveIds.length;
  const transferWarning = activity.list.isError || Object.values(activity.list.data?.errors || {}).some(Boolean);
  const transfersOpen = keepTransfersOpen || openId !== null || liveIds.some(id => !dismissedTransfers.has(id));
  const provider = selectedProvider && configuration[selectedProvider].enabled
    ? selectedProvider : providers.find(item => configuration[item].enabled);
  const service = provider ? configuration[provider] : undefined;

  useLayoutEffect(() => {
    if (!focusProvider.current) return;
    focusProvider.current = false;
    activeProviderTab.current?.focus({ preventScroll: true });
  }, [provider]);

  /** Restore focus to the active source after switching the keyed browser pane. */
  function chooseProvider(next: CloudFileProvider) {
    if (next === provider) return;
    focusProvider.current = true;
    setSelectedProvider(next);
  }

  /** Fold explicitly and restore the toolbar entry, preserving a newly discovered task's ability to reveal the pane. */
  function collapseTransfers() {
    setOpenId(null);
    setKeepTransfersOpen(false);
    setLedgerFocus(null);
    setDismissedTransfers(new Set(liveIds));
    transferTrigger.current?.focus({ preventScroll: !window.matchMedia('(max-width: 860px)').matches });
  }

  /** Open the current receipt in the ledger and focus its row without changing the file selection. */
  function revealTransfer(id: string | null) {
    setKeepTransfersOpen(true);
    setOpenId(id);
    setLedgerFocus({ id });
  }

  /** Show a new receipt immediately while the native state is polled independently. */
  function openReceipt(receipt: CloudCopySubmission, destination: string) {
    setReceipt({ result: receipt, destination });
    if (!('id' in receipt)) return;
    queries.setQueryData([...cloudTransfersKey, receipt.id], receipt);
    const now = Date.now();
    setRecent(current => [{ receipt, expires: now + nativeDiscoveryWindow },
      ...current.filter(item => item.receipt.id !== receipt.id && item.expires > now)].slice(0, 30));
    setOpenId(receipt.id);
    void queries.invalidateQueries({ queryKey: cloudTransfersKey });
  }

  const receiptTransfer = receipt && 'id' in receipt.result ? receipt.result : null;
  const browserReady = Boolean(provider && service && configuration.local_root && configuration.enabled);
  const sourceTabs = <div className="nfc-cloud-provider-control" role="group" aria-label="云端来源" data-provider={provider}>
    {providers.map(item => (
      <ConsoleButton key={item} ref={provider === item ? activeProviderTab : undefined} size="sm" variant="ghost"
        disabled={!configuration[item].enabled || submitting} aria-pressed={provider === item}
        onClick={() => chooseProvider(item)}>{providerLabel[item]}</ConsoleButton>
    ))}
  </div>;
  const transferToggle = <ConsoleButton ref={transferTrigger} size="sm" variant="ghost" className="nfc-cloud-transfer-trigger"
    title="传输任务" aria-label="传输任务" aria-expanded={transfersOpen} aria-describedby="nfc-cloud-transfer-summary"
    aria-controls={transfersOpen ? 'nfc-cloud-files-transfers' : undefined}
    leadingIcon={<ConsoleIcon name="activity" size={16} />}
    onClick={() => {
      if (transfersOpen) collapseTransfers();
      else if (window.matchMedia('(max-width: 860px)').matches) revealTransfer(null);
      else setKeepTransfersOpen(true);
    }}>
    <span>传输任务</span>
    <span className="nfc-cloud-transfer-trigger-count" id="nfc-cloud-transfer-summary">
      {liveIds.length > 0 ? liveIds.length + ' 个进行中' : historyCount > 0
        ? historyCount + ' 条记录' : activity.list.isPending ? '读取中' : '无任务'}
      {transferWarning && <span className="nfc-cloud-transfer-trigger-warning"> · 读取异常</span>}
    </span>
  </ConsoleButton>;
  const receiptNotice = receipt && <CloudCopyNotice tone={receiptTransfer?.error ? 'warning' : 'success'}
    title={formatCloudSubmission(receipt.result)}
    action={receiptTransfer && <ConsoleButton size="sm" variant={receiptTransfer.error ? 'secondary' : 'primary'}
      onClick={() => revealTransfer(receiptTransfer.id)} leadingIcon={<ConsoleIcon name="arrow-right" size={15} />}>
      查看传输
    </ConsoleButton>}>
    <span>NAS 目标 <code>{receipt.destination}</code></span>
    {receiptTransfer?.error && <div>请先核对原生传输的结果，再重新选择要提交的项目。</div>}
  </CloudCopyNotice>;
  return (
    <div className="nfc-cloud-files-layout" data-transfers-open={transfersOpen ? 'true' : undefined}
      data-browser-ready={browserReady || undefined} data-has-copy-receipt={Boolean(receipt) || undefined}>
      <div className="nfc-cloud-files-sources">
        {provider && service && configuration.local_root && configuration.enabled ? (
          <CloudBrowser key={provider + '/' + configuration.local_root} provider={provider}
            name={service.name || providerLabel[provider]} localRoot={configuration.local_root}
            sourceTabs={sourceTabs} transferToggle={transferToggle} receiptNotice={receiptNotice}
            writable={configuration.writable} onSubmitted={openReceipt}
            onSubmitStart={() => { setReceipt(null); setSubmitting(true); }}
            onSubmitFinish={() => setSubmitting(false)} onViewTransfers={() => revealTransfer(null)} />
        ) : <>
          <div className="nfc-cloud-provider-switch">{sourceTabs}{transferToggle}</div>
          <DataPanel title="云端目录"><ConsoleEmpty title="云端复制尚未配置"
            description="为此部署配置 OpenList 或 rclone，以及允许写入的 NAS 目录。" /></DataPanel>
        </>}
      </div>
      {transfersOpen && <TransferLedger configuration={configuration} activity={activity}
        openId={openId} onOpen={setOpenId} focusRequest={ledgerFocus} onInteract={() => setKeepTransfersOpen(true)}
        onCollapse={collapseTransfers} onDismissReceipt={id => {
          setRecent(current => current.filter(item => item.receipt.id !== id));
          if (receiptTransfer?.id === id) setReceipt(null);
        }} />}
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
