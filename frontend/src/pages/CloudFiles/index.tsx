import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { DataPanel } from '../../components/ui/DataPanel';
import { PageHeader } from '../../components/ui/PageHeader';

import { cloudFilesApi, type CloudFileProvider, type CloudFilesConfiguration, type CloudTransfer } from '../../api/cloudFiles';

import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { CloudBrowser } from './CloudBrowser';
import { cloudTransfersKey, TransferLedger, type RecentTransfer } from './TransferLedger';
import { providerLabel } from './presentation';

const providers = ['openlist', 'rclone'] as const;
const nativeDiscoveryWindow = 20_000;

/** Present selection and the native task ledger in the same independent workspace. */
function CloudWorkspace({ configuration }: { configuration: CloudFilesConfiguration }) {
  const queries = useQueryClient();
  const [selectedProvider, setSelectedProvider] = useState<CloudFileProvider | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentTransfer[]>([]);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const provider = selectedProvider && configuration[selectedProvider].enabled
    ? selectedProvider : providers.find(item => configuration[item].enabled);
  const service = provider ? configuration[provider] : undefined;

  /** Show a new receipt immediately while the native state is polled independently. */
  function openReceipt(receipt: CloudTransfer) {
    setSubmissionError(receipt.error);
    queries.setQueryData([...cloudTransfersKey, receipt.id], receipt);
    const now = Date.now();
    setRecent(current => [{ receipt, expires: now + nativeDiscoveryWindow },
      ...current.filter(item => item.receipt.id !== receipt.id && item.expires > now)].slice(0, 30));
    setOpenId(receipt.id);
    void queries.invalidateQueries({ queryKey: cloudTransfersKey });
  }

  return (
    <div className="nfc-cloud-files-layout">
      <div className="nfc-cloud-files-sources">
        <div className="nfc-tool-segment" role="group" aria-label="云端来源">
          {providers.map(item => (
            <ConsoleButton key={item} variant="ghost" disabled={!configuration[item].enabled}
              aria-pressed={provider === item} onClick={() => setSelectedProvider(item)}>{providerLabel[item]}</ConsoleButton>
          ))}
        </div>
        {submissionError && <p className="nfc-cloud-files-error" role="alert">{submissionError}</p>}
        {provider && service && configuration.local_root && configuration.enabled ? (
          <CloudBrowser key={provider + '/' + configuration.local_root} provider={provider}
            name={service.name || providerLabel[provider]} localRoot={configuration.local_root}
            writable={configuration.writable} onStarted={openReceipt} />
        ) : <DataPanel title="云端目录"><ConsoleEmpty title="云端复制尚未配置"
          description="为此部署配置 OpenList 或 rclone，以及允许写入的 NAS 目录。" /></DataPanel>}
      </div>
      <TransferLedger configuration={configuration} openId={openId} onOpen={setOpenId} recent={recent}
        onDismissReceipt={id => setRecent(current => current.filter(item => item.receipt.id !== id))} />
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
      <PageHeader title="云端文件" description="从 OpenList 或 rclone 选择文件，复制到 NAS 并查看原生任务进度。"
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
