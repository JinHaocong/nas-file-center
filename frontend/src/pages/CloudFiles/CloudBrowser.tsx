import { Fragment, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { DirectoryPicker } from '../../components/DirectoryPicker';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleCheckbox } from '../../components/ui/ConsoleCheckbox';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleSelect } from '../../components/ui/ConsoleSelect';
import { DataPanel } from '../../components/ui/DataPanel';

import { cloudFilesApi, type CloudFileProvider, type CloudTransfer } from '../../api/cloudFiles';
import { getStructuredApiError } from '../../api/errors';

import { displayBytes, providerLabel } from './presentation';

const selectionLimit = 30;
const pageSize = 60;
const sortNames = new Intl.Collator('zh-CN', { numeric: true });

interface Props {
  provider: CloudFileProvider;
  name: string;
  localRoot: string;
  writable: boolean;
  onStarted: (transfer: CloudTransfer) => void;
}

/** Browse one provider and submit the visible selection to an allowed NAS directory. */
export function CloudBrowser({ provider, name, localRoot, writable, onStarted }: Props) {
  const [remoteChoice, setRemoteChoice] = useState('');
  const [path, setPath] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [names, setNames] = useState<string[]>([]);
  const [destination, setDestination] = useState(localRoot);
  const [error, setError] = useState('');
  const locationRef = useRef<HTMLElement>(null);
  const inFlight = useRef(false);

  const remotes = useQuery({
    queryKey: ['cloud-files', 'remotes'], queryFn: cloudFilesApi.remotes,
    enabled: provider === 'rclone', staleTime: 30_000, retry: false,
  });
  const availableRemotes = remotes.data?.items;
  const remote = provider === 'rclone'
    ? remoteChoice ? availableRemotes?.find(item => item.name === remoteChoice)?.name : availableRemotes?.[0]?.name
    : undefined;
  const canBrowse = provider === 'openlist' || Boolean(remote);
  const browse = useQuery({
    queryKey: ['cloud-files', 'entries', provider, remote, path],
    queryFn: () => cloudFilesApi.entries(provider, remote, path),
    enabled: canBrowse, staleTime: 5_000, retry: false,
  });
  const entries = useMemo(() => (browse.data?.items || []).slice().sort((left, right) => {
    if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1;
    return sortNames.compare(left.name, right.name);
  }), [browse.data]);
  const matched = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return query ? entries.filter(entry => entry.name.toLocaleLowerCase().includes(query)) : entries;
  }, [entries, search]);
  const selected = useMemo(() => {
    const visible = new Set(entries.map(entry => entry.name));
    return names.filter(name => visible.has(name));
  }, [names, entries]);

  const start = useMutation({ mutationFn: cloudFilesApi.start });
  const insideRoot = destination === localRoot || destination.startsWith(localRoot + '/');
  const canStart = writable && canBrowse && browse.isSuccess && !browse.isFetching && insideRoot &&
    selected.length > 0 && selected.length <= selectionLimit;
  const parts = path === '' ? [] : path.split('/');
  const label = provider === 'rclone' ? remote || providerLabel.rclone : name;

  /** Navigate with a fresh selection and retain keyboard focus on the location breadcrumb. */
  function openDirectory(next: string) {
    setPath(next);
    setSearch('');
    setPage(1);
    setNames([]);
    setError('');
    locationRef.current?.focus({ preventScroll: true });
  }

  /** A response may fail after the provider has accepted it, so never retry automatically. */
  async function submit() {
    if (!canStart || inFlight.current) return;
    inFlight.current = true;
    setError('');
    try {
      const receipt = await start.mutateAsync({ provider, remote, path, names: selected, destination });
      setNames([]);
      if (receipt.error) setError(receipt.error);
      onStarted(receipt);
    } catch (failure) {
      setError(getStructuredApiError(failure).message || '提交状态暂时无法确认，请先查看传输任务。');
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <DataPanel title="云端目录" id="nfc-cloud-files-browser" className="nfc-cloud-files-browser">
      {provider === 'rclone' && (
        <div className="nfc-cloud-files-remote">
          {remotes.isPending && <p className="nfc-cloud-files-muted" role="status">正在读取远程存储…</p>}
          {remotes.isError && <div className="nfc-cloud-files-failure" role="alert">
            <span>无法读取 rclone 远程存储。</span>
            <ConsoleButton size="sm" onClick={() => { void remotes.refetch(); }}>重试</ConsoleButton>
          </div>}
          {remotes.isSuccess && (availableRemotes?.length ? (
            <ConsoleSelect id="nfc-cloud-files-remote" label="远程存储" value={remote || ''}
              disabled={start.isPending}
              options={[
                ...(!remote ? [{ label: '请选择远程存储', value: '', disabled: true }] : []),
                ...availableRemotes.map(item => ({ label: item.name, value: item.name })),
              ]}
              onChange={value => { setRemoteChoice(value); openDirectory(''); }} />
          ) : <ConsoleEmpty title="没有可用的远程存储" />)}
        </div>
      )}
      {canBrowse && <>
        <div className="nfc-cloud-files-toolbar">
          <nav ref={locationRef} tabIndex={-1} className="nfc-cloud-files-crumb"
            aria-label="当前云端位置">
            <button type="button" className="nfc-v2-breadcrumb-link" disabled={start.isPending || !path}
              aria-current={path ? undefined : 'location'} onClick={() => openDirectory('')}>
              <ConsoleIcon name="cloud" size={16} /><span>{label}</span>
            </button>
            {parts.map((part, i) => {
              const crumbPath = parts.slice(0, i + 1).join('/');
              return <Fragment key={crumbPath}>
                <ConsoleIcon name="chevron-right" size={14} />
                {i === parts.length - 1 ? <strong aria-current="location">{part}</strong> :
                  <button type="button" className="nfc-v2-breadcrumb-link" disabled={start.isPending}
                    onClick={() => openDirectory(crumbPath)}>{part}</button>}
              </Fragment>;
            })}
          </nav>
          <ConsoleButton variant="ghost" size="sm" leadingIcon={<ConsoleIcon name="refresh" size={15} />}
            disabled={browse.isFetching || start.isPending} onClick={() => { void browse.refetch(); }}>刷新</ConsoleButton>
        </div>
        <div className="nfc-directory-search-row nfc-cloud-files-search">
          <ConsoleIcon name="search" size={15} />
          <input type="search" aria-label="筛选当前云端目录" value={search}
            placeholder="筛选当前目录" onChange={event => { setSearch(event.target.value); setPage(1); }} />
        </div>
        <div className="nfc-cloud-files-list-area" aria-busy={browse.isFetching || undefined}>
          {browse.isPending && <p role="status" className="nfc-cloud-files-muted">正在读取目录…</p>}
          {browse.isError && <div className="nfc-cloud-files-failure" role="alert">
            <span>{getStructuredApiError(browse.error).message || '无法读取此目录。'}</span>
            <ConsoleButton size="sm" onClick={() => { void browse.refetch(); }}>重试</ConsoleButton>
          </div>}
          {browse.isSuccess && (matched.length === 0 ? (
            <ConsoleEmpty title={search ? '没有匹配的项目' : '此目录为空'} />
          ) : <>
            <ul className="nfc-cloud-files-entries" aria-label="目录中的文件和文件夹">
              {matched.slice(0, page * pageSize).map(entry => {
                const checked = selected.includes(entry.name);
                return <li key={entry.name} className={checked ? 'is-selected' : undefined}>
                  <ConsoleCheckbox checked={checked} aria-label={'选择 ' + entry.name}
                    disabled={!writable || start.isPending || (!checked && selected.length >= selectionLimit)}
                    onCheckedChange={checked => setNames(previous => checked
                      ? selected.length >= selectionLimit ? previous : [...new Set([...previous, entry.name])]
                      : previous.filter(name => name !== entry.name))} />
                  {entry.kind === 'directory' ? (
                    <button className="nfc-cloud-file-name" type="button" disabled={start.isPending}
                      onClick={() => openDirectory(parts.concat(entry.name).join('/'))}>
                      <ConsoleIcon name="folder" size={17} /><span>{entry.name}</span>
                      <ConsoleIcon name="chevron-right" size={14} />
                    </button>
                  ) : <span className="nfc-cloud-file-name">
                    <ConsoleIcon name="file-text" size={17} /><span>{entry.name}</span>
                  </span>}
                  <small className="nfc-cloud-files-muted">{entry.kind === 'directory' ? '文件夹' : displayBytes(entry.size)}</small>
                </li>;
              })}
            </ul>
            {matched.length > page * pageSize && <ConsoleButton size="sm" variant="ghost"
              className="nfc-cloud-files-more" onClick={() => setPage(value => value + 1)}>
              显示更多（{page * pageSize} / {matched.length}）
            </ConsoleButton>}
          </>)}
        </div>
        <div className="nfc-cloud-files-destination" role="group" aria-label="NAS 存放位置">
          <strong>NAS 存放位置</strong>
          <DirectoryPicker value={destination} allowManualInput={false} disabled={!writable || start.isPending}
            onChange={(value: string | string[]) => setDestination(typeof value === 'string' ? value : value[0] || '')} />
          {writable && destination && !insideRoot &&
            <p role="alert" className="nfc-cloud-files-error">请选择 {localRoot} 内的目录。</p>}
          {error && <p role="alert" className="nfc-cloud-files-error">{error}</p>}
          <div className="nfc-cloud-files-submit">
            <small className="nfc-cloud-files-muted" role="status">
              {!writable ? '当前部署为只读模式。' : selected.length === selectionLimit
                ? '已选 ' + selectionLimit + ' 项（已达单次上限）' : '已选 ' + selected.length + ' 项'}
            </small>
            <ConsoleButton variant="primary" disabled={!canStart} loading={start.isPending}
              leadingIcon={<ConsoleIcon name="arrow-down" size={17} />}
              onClick={() => { void submit(); }}>复制到 NAS</ConsoleButton>
          </div>
        </div>
      </>}
    </DataPanel>
  );
}
