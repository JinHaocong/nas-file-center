import { useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { DirectoryPicker } from '../../components/DirectoryPicker';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { DataPanel } from '../../components/ui/DataPanel';
import { PageHeader } from '../../components/ui/PageHeader';
import { RemoteDirectoryPicker } from './RemoteDirectoryPicker';

import { cloudCopyApi } from '../../api/cloudCopy';
import { downloadVerificationApi } from '../../api/downloadVerification';
import { getStructuredApiError } from '../../api/errors';
import { useTitle } from '../../hooks/useTitle';

interface FormProps {
  sourceId: string;
  sourceName: string;
  localRoot: string;
}

/** Choose a cloud folder and a new, non-overlapping destination on the NAS. */
function CloudCopyForm({ sourceId, sourceName, localRoot }: FormProps) {
  const navigate = useNavigate();
  const [remote, setRemote] = useState('');
  const [localParent, setLocalParent] = useState(localRoot);
  const [name, setName] = useState('');
  const [selecting, setSelecting] = useState(false);
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const copying = useRef(false);
  const opener = useRef<HTMLButtonElement | null>(null);

  const resultName = name.trim();
  const allowedParent = localParent === localRoot || localParent.startsWith(localRoot + '/');
  const validName = resultName !== '' && resultName !== '.' && resultName !== '..' &&
    !resultName.toLowerCase().startsWith('.nfc-') && !/[\/\\\u0000-\u001f]/.test(resultName);
  const ready = Boolean(remote && allowedParent && validName);

  /** Submit the exact selection once, then open its persisted task. */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || copying.current) return;
    copying.current = true;
    setSubmitting(true);
    setError('');
    try {
      const job = await cloudCopyApi.start({
        source_id: sourceId, remote_root: remote, local_parent: localParent, folder_name: resultName,
      });
      navigate('/tasks?' + new URLSearchParams({ task: job.job_id }));
    } catch (failure) {
      setError(getStructuredApiError(failure).message || '无法创建复制任务，请重试。');
    } finally {
      copying.current = false;
      setSubmitting(false);
    }
  }

  return <>
    <form className="nfc-dv-workspace" onSubmit={event => { void submit(event); }}
      aria-busy={isSubmitting || undefined}>
      <div className="nfc-dv-pair">
        <div className="nfc-dv-pair-card">
          <div className="nfc-dv-pair-heading"><ConsoleIcon name="folder-open" size={17} /> {sourceName}</div>
          <div className="nfc-dv-field">
            <label htmlFor="nfc-cloud-copy-source">云端目录</label>
            <div className="nfc-dv-control-row">
              <input id="nfc-cloud-copy-source" value={remote ? '/' + remote : ''} placeholder="请选择云端文件夹"
                readOnly />
              <ConsoleButton disabled={isSubmitting} onClick={event => {
                opener.current = event.currentTarget;
                setSelecting(true);
              }}>选择云端目录</ConsoleButton>
            </div>
          </div>
        </div>
        <ConsoleIcon className="nfc-dv-pair-connector" name="arrow-right" size={18} />
        <div className="nfc-dv-pair-card">
          <div className="nfc-dv-pair-heading"><ConsoleIcon name="hard-drive" size={17} /> NAS 目标目录</div>
          <div className="nfc-dv-field" role="group" aria-label="NAS 上级目录">
            <DirectoryPicker value={localParent} allowManualInput={false} disabled={isSubmitting}
              onChange={value => setLocalParent(typeof value === 'string' ? value : value[0] || '')} />
            <small>可以选择 {localRoot} 或它下面的文件夹。</small>
          </div>
          <div className="nfc-dv-field">
            <label htmlFor="nfc-cloud-copy-name">新文件夹名称</label>
            <input id="nfc-cloud-copy-name" value={name} required maxLength={255} disabled={isSubmitting}
              onChange={event => setName(event.target.value)} />
          </div>
        </div>
      </div>
      {ready && <div className="nfc-dv-field">
        <span>完成后可在这里找到文件</span>
        <CodePath value={localParent + '/' + resultName} />
      </div>}
      {localParent && !allowedParent && <p role="alert" className="nfc-dv-error">请选择允许的 NAS 存放位置。</p>}
      {!!resultName && !validName && <p role="alert" className="nfc-dv-error">请输入有效的新文件夹名称。</p>}
      {error && <p role="alert" className="nfc-dv-error">{error}</p>}
      <div className="nfc-dv-footer">
        <p>复制完成后会生成一个新文件夹。如果同名目录已经存在，请换一个名称。</p>
        <ConsoleButton variant="primary" type="submit" loading={isSubmitting} disabled={!ready}
          leadingIcon={<ConsoleIcon name="arrow-down" size={16} />}>开始复制到 NAS</ConsoleButton>
      </div>
    </form>
    <RemoteDirectoryPicker open={selecting} sourceId={sourceId} sourceName={sourceName} initialPath={remote}
      onClose={() => setSelecting(false)} returnFocusTo={opener.current} onConfirm={path => {
        setRemote(path);
        setName(path.split('/').at(-1) || '');
        setError('');
      }} />
  </>;
}

/** Use the deployment-authorized OpenList source and landing root. */
export function CloudCopyWorkspace() {
  useTitle('云端复制到 NAS');
  const navigate = useNavigate();
  const configuration = useQuery({
    queryKey: ['cloud-copy-configuration'], queryFn: cloudCopyApi.configuration, retry: false,
  });
  const sources = useQuery({
    queryKey: ['download-verify-sources'], queryFn: downloadVerificationApi.sources,
    enabled: configuration.data?.configured === true,
  });
  const config = configuration.data;
  const source = sources.data?.items.find(item => item.active && item.provider === 'openlist' &&
    (item.id_text ?? String(item.id)) === config?.source_id);
  return (
    <div className="nfc-operations-page nfc-page-layout-workbench nfc-download-verify nfc-download-verify-page nfc-tool-workspace">
      <PageHeader title="云端复制到 NAS"
        description="从 OpenList 选择目录，rclone 会在后台复制，进度可以在任务中心查看。"
        actions={<ConsoleButton onClick={() => navigate('/download-verification')}>下载校验</ConsoleButton>} />
      <DataPanel title="新建复制任务">
        {(configuration.isPending || (config?.configured && sources.isPending)) &&
          <p role="status">正在读取复制设置…</p>}
        {configuration.isError && <div role="alert">
          <p>无法读取云端复制设置。</p>
          <ConsoleButton onClick={() => { void configuration.refetch(); }}>重试</ConsoleButton>
        </div>}
        {sources.isError && <p role="alert">无法读取 OpenList 来源，请重试或检查来源设置。</p>}
        {config?.configured === false && <p>云端复制尚未配置。请为此部署配置 OpenList 来源、rclone 和 NAS 存放位置。</p>}
        {config?.configured && sources.isSuccess && !source && <div>
          <p>配置中的 OpenList 来源不可用。</p>
          <ConsoleButton onClick={() => navigate('/download-sources')}>管理来源</ConsoleButton>
        </div>}
        {config?.configured && config.source_id && config.local_root && source && (
          <CloudCopyForm key={config.source_id + config.local_root} sourceId={config.source_id}
            sourceName={source.name} localRoot={config.local_root} />
        )}
      </DataPanel>
    </div>
  );
}
