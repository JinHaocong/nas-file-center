import { Fragment, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import * as Dialog from '@radix-ui/react-dialog';

import { DirectoryPickerModal } from '../../components/DirectoryPicker';
import { isWithinDirectoryRoots } from '../../components/DirectoryPicker/selection_model';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleCheckbox } from '../../components/ui/ConsoleCheckbox';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleSelect } from '../../components/ui/ConsoleSelect';

import { cloudFilesApi, type CloudCopySubmission, type CloudEntry, type CloudFileProvider } from '../../api/cloudFiles';
import { getStructuredApiError } from '../../api/errors';

import { displayBytes } from './presentation';

const selectionLimit = 30;
const pageSize = 60;
const sortNames = new Intl.Collator('zh-CN', { numeric: true });

/** Show the directory affordance separately from the file type. */
function CloudEntryIcon({ kind }: { kind: CloudEntry['kind'] }) {
  return <span className="nfc-cloud-entry-icon" data-kind={kind}>
    <ConsoleIcon name={kind === 'directory' ? 'folder' : 'file-text'} size={15} />
  </span>;
}

interface Props {
  provider: CloudFileProvider;
  name: string;
  localRoot: string;
  writable: boolean;
  onSubmitted: (receipt: CloudCopySubmission) => void;
}

/** Browse one provider and submit the visible selection to an allowed NAS directory. */
export function CloudBrowser({ provider, name, localRoot, writable, onSubmitted }: Props) {
  const [remoteChoice, setRemoteChoice] = useState('');
  const [path, setPath] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [names, setNames] = useState<string[]>([]);
  const [destination, setDestination] = useState(localRoot);
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyStep, setCopyStep] = useState<'review' | 'target'>('review');
  const [pickerBusy, setPickerBusy] = useState(false);
  const [error, setError] = useState('');
  const [skippedCount, setSkippedCount] = useState(0);
  const locationRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const selectionFocus = useRef<HTMLInputElement | null>(null);
  const copyTrigger = useRef<HTMLButtonElement>(null);
  const targetButton = useRef<HTMLButtonElement>(null);
  const targetHeading = useRef<HTMLHeadingElement>(null);
  const focusCopyStep = useRef(false);
  const lastReview = useRef<CloudEntry[]>([]);
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
  const selectedEntries = useMemo(() => {
    const byName = new Map(entries.map(entry => [entry.name, entry]));
    return names.flatMap(name => {
      const entry = byName.get(name);
      return entry ? [entry] : [];
    });
  }, [names, entries]);
  const selected = useMemo(() => selectedEntries.map(entry => entry.name), [selectedEntries]);

  const start = useMutation({ mutationFn: cloudFilesApi.start });
  const insideRoot = isWithinDirectoryRoots(destination, [localRoot]);
  const canReview = writable && canBrowse && browse.isSuccess && !browse.isFetching &&
    selected.length > 0 && selected.length <= selectionLimit;
  const canStart = canReview && insideRoot;
  const dialogBusy = start.isPending || (copyStep === 'target' && pickerBusy);
  const reviewEntries = copyOpen ? selectedEntries : lastReview.current;
  const parts = path === '' ? [] : path.split('/');
  const label = provider === 'rclone' ? '根目录' : name;

  useLayoutEffect(() => {
    if (copyOpen) lastReview.current = selectedEntries;
    if (!copyOpen || !focusCopyStep.current) return;
    focusCopyStep.current = false;
    (copyStep === 'target' ? targetHeading.current : targetButton.current)?.focus({ preventScroll: true });
  }, [copyOpen, copyStep, selectedEntries]);

  /** Move keyboard focus before removing a selection action or after a copy completes. */
  function restoreSelectionFocus() {
    const checkbox = selectionFocus.current;
    if (checkbox?.isConnected && !checkbox.disabled) checkbox.focus({ preventScroll: true });
    else listRef.current?.focus({ preventScroll: true });
  }

  /** Swap steps without opening another modal or moving the file browser. */
  function showCopyStep(next: 'review' | 'target') {
    focusCopyStep.current = true;
    setCopyStep(next);
  }

  /** Keep filtering local to the current directory and return the viewport to its first row. */
  function filterDirectory(value: string) {
    setSearch(value);
    setPage(1);
    listRef.current?.scrollTo({ top: 0 });
  }

  /** Navigate with a fresh selection and retain keyboard focus on the location breadcrumb. */
  function openDirectory(next: string) {
    setPath(next);
    setSearch('');
    setPage(1);
    setNames([]);
    setError('');
    setSkippedCount(0);
    listRef.current?.scrollTo({ top: 0 });
    locationRef.current?.focus({ preventScroll: true });
  }

  /** A response may fail after the provider has accepted it, so never retry automatically. */
  async function submit() {
    if (!canStart || inFlight.current) return;
    inFlight.current = true;
    setError('');
    setSkippedCount(0);
    try {
      const receipt = await start.mutateAsync({ provider, remote, path, names: selected, destination });
      setCopyOpen(false);
      setNames([]);
      setSkippedCount(receipt.skipped_names?.length ?? 0);
      onSubmitted(receipt);
    } catch (failure) {
      setError(getStructuredApiError(failure).message || '提交状态暂时无法确认，请先查看传输任务。');
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <Dialog.Root open={copyOpen} onOpenChange={open => {
      if (dialogBusy) return;
      if (open) {
        focusCopyStep.current = false;
        setCopyStep('review');
        setError('');
      }
      setCopyOpen(open);
    }}>
      <section id="nfc-cloud-files-browser" className="nfc-cloud-files-browser" aria-label="云端目录">
        <div className="nfc-cloud-files-browser-tools">
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
                {path ? <button type="button" disabled={start.isPending} onClick={() => openDirectory('')}>
                  <ConsoleIcon name="cloud" size={16} /><span>{label}</span>
                </button> : <strong aria-current="location"><ConsoleIcon name="cloud" size={16} /><span>{label}</span></strong>}
                {parts.map((part, i) => {
                  const crumbPath = parts.slice(0, i + 1).join('/');
                  return <Fragment key={crumbPath}>
                    <ConsoleIcon name="chevron-right" size={14} />
                    {i === parts.length - 1 ? <strong aria-current="location">{part}</strong> :
                      <button type="button" disabled={start.isPending}
                        onClick={() => openDirectory(crumbPath)}>{part}</button>}
                  </Fragment>;
                })}
              </nav>
              <div className="nfc-cloud-files-tools-actions">
                <label className="nfc-cloud-files-search">
                  <ConsoleIcon name="search" size={16} />
                  <input type="search" aria-label="筛选当前云端目录" value={search}
                    placeholder="筛选目录" onChange={event => filterDirectory(event.target.value)}
                    onKeyDown={event => {
                      if (event.key === 'Escape' && search) {
                        event.preventDefault();
                        filterDirectory('');
                      }
                    }} />
                </label>
                <ConsoleButton variant="ghost" size="sm" leadingIcon={<ConsoleIcon name="refresh" size={16} />}
                  aria-label="刷新目录" disabled={browse.isFetching || start.isPending}
                  loading={browse.isRefetching}
                  onClick={() => { void browse.refetch(); }} />
              </div>
            </div>
          </>}
        </div>
        {canBrowse && <>
          <div className="nfc-cloud-files-columns" aria-hidden="true"><span>名称</span><span>大小</span></div>
          <div ref={listRef} className="nfc-cloud-files-list-area" role="region" aria-label="云端文件列表" tabIndex={0}
            aria-busy={browse.isFetching || undefined}>
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
                    <label className="nfc-cloud-selection-hit">
                      <ConsoleCheckbox checked={checked} aria-label={'选择 ' + entry.name}
                        disabled={!writable || start.isPending || (!checked && selected.length >= selectionLimit)}
                        onFocus={event => { selectionFocus.current = event.currentTarget; }}
                        onCheckedChange={checked => setNames(previous => checked
                          ? selected.length >= selectionLimit ? previous : [...new Set([...previous, entry.name])]
                          : previous.filter(name => name !== entry.name))} />
                    </label>
                    {entry.kind === 'directory' ? (
                      <button className="nfc-cloud-file-name" type="button" disabled={start.isPending}
                        onClick={() => openDirectory(parts.concat(entry.name).join('/'))}>
                        <CloudEntryIcon kind={entry.kind} /><span>{entry.name}</span>
                        <ConsoleIcon name="chevron-right" size={14} className="nfc-cloud-file-chevron" />
                      </button>
                    ) : <span className="nfc-cloud-file-name">
                      <CloudEntryIcon kind={entry.kind} /><span>{entry.name}</span>
                    </span>}
                    <small className="nfc-cloud-file-size">{entry.kind === 'directory' ? '—' : displayBytes(entry.size)}</small>
                  </li>;
                })}
              </ul>
              {matched.length > page * pageSize && <ConsoleButton size="sm" variant="ghost"
                className="nfc-cloud-files-more" onClick={() => setPage(value => value + 1)}>
                显示更多（{page * pageSize} / {matched.length}）
              </ConsoleButton>}
            </>)}
          </div>
          {selected.length > 0 ? <footer className="nfc-cloud-files-destination nfc-cloud-selection-actions">
            <div className="nfc-cloud-files-submit">
              <div className="nfc-cloud-selection-status">
                <small className="nfc-cloud-files-muted" role="status">
                  已选 {selected.length} 项{selected.length === selectionLimit && '（单次上限）'}
                </small>
                <ConsoleButton size="sm" variant="ghost" disabled={start.isPending}
                  onClick={() => {
                    setNames([]);
                    restoreSelectionFocus();
                  }}>清除选择</ConsoleButton>
              </div>
              <Dialog.Trigger asChild>
                <ConsoleButton ref={copyTrigger} variant="primary" disabled={!canReview || start.isPending}
                  leadingIcon={<ConsoleIcon name="arrow-down" size={17} />}>复制到 NAS</ConsoleButton>
              </Dialog.Trigger>
            </div>
          </footer> : <footer className="nfc-cloud-files-destination nfc-cloud-idle-footer">
            <small className="nfc-cloud-files-muted" role="status">
              {!writable ? '只读模式' : skippedCount > 0 ? '已跳过 ' + skippedCount + ' 个已有文件'
                : (search ? matched.length + ' 项匹配' : entries.length + ' 项')}
            </small>
          </footer>}
        </>}
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-cloud-copy-overlay" />
          <Dialog.Content className="nfc-v2-dialog nfc-overlay-modal nfc-cloud-copy-dialog" data-copy-step={copyStep}
            aria-describedby={undefined} aria-busy={dialogBusy || undefined}
            onEscapeKeyDown={event => {
              if (dialogBusy || copyStep === 'target') event.preventDefault();
              if (!dialogBusy && copyStep === 'target') showCopyStep('review');
            }}
            onCloseAutoFocus={event => {
              if (copyTrigger.current?.isConnected && !copyTrigger.current.disabled) return;
              event.preventDefault();
              restoreSelectionFocus();
            }}
            onPointerDownOutside={event => event.preventDefault()}>
            <header className="nfc-cloud-copy-header">
              <div className="nfc-cloud-copy-title">
                <span><ConsoleIcon name="arrow-down" size={19} /></span>
                <Dialog.Title>复制到 NAS</Dialog.Title>
              </div>
              <Dialog.Close asChild>
                <button type="button" className="nfc-v2-dialog-close" aria-label="关闭复制窗口" disabled={dialogBusy}>
                  <ConsoleIcon name="x" size={19} />
                </button>
              </Dialog.Close>
            </header>
            {copyStep === 'target' ? <>
              <h3 className="nfc-cloud-copy-step-title" ref={targetHeading} tabIndex={-1}>选择 NAS 目录</h3>
              <DirectoryPickerModal open={copyOpen} inline={{ rootPath: localRoot, onBusyChange: setPickerBusy }}
                initialPath={insideRoot ? destination : localRoot} selectedValues={destination}
                onConfirm={value => { if (typeof value === 'string') setDestination(value); }}
                onCancel={() => showCopyStep('review')} />
            </> : <>
              <div className="nfc-cloud-copy-content">
                <section aria-labelledby="nfc-cloud-copy-selected" className="nfc-cloud-copy-items">
                  <h3 id="nfc-cloud-copy-selected">已选 {reviewEntries.length} 项</h3>
                  <ul className="nfc-cloud-copy-selection">
                    {reviewEntries.map(entry => <li key={entry.name}>
                      <CloudEntryIcon kind={entry.kind} />
                      <span>{entry.name}</span>
                      <small className="nfc-cloud-file-size">{entry.kind === 'directory' ? '文件夹' : displayBytes(entry.size)}</small>
                    </li>)}
                  </ul>
                </section>
                <section role="group" aria-label="NAS 存放位置">
                  <h3>NAS 存放位置</h3>
                  <div className="nfc-cloud-copy-target">
                    <span><ConsoleIcon name="folder" size={16} />{destination}</span>
                    <ConsoleButton ref={targetButton} size="sm" disabled={start.isPending}
                      onClick={() => showCopyStep('target')}>选择目录</ConsoleButton>
                  </div>
                  {destination && !insideRoot &&
                    <p role="alert" className="nfc-cloud-files-error">请选择 {localRoot} 内的目录。</p>}
                </section>
                {error && <p role="alert" className="nfc-cloud-files-error">{error}</p>}
              </div>
              <footer className="nfc-cloud-copy-actions">
                <Dialog.Close asChild><ConsoleButton disabled={start.isPending}>取消</ConsoleButton></Dialog.Close>
                <ConsoleButton variant="primary" disabled={!canStart} loading={start.isPending}
                  leadingIcon={<ConsoleIcon name="arrow-down" size={16} />}
                  onClick={() => { void submit(); }}>{start.isPending ? '正在提交' : '开始复制'}</ConsoleButton>
              </footer>
            </>}
          </Dialog.Content>
        </Dialog.Portal>
      </section>
    </Dialog.Root>
  );
}
