import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';

import { PathBreadcrumb } from '../../components/DirectoryPicker';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleSheet } from '../../components/ui/ConsoleSheet';
import { MediaThumbnail, ThumbnailSwitch } from '../../components/ui/MediaThumbnail';
import { StoragePreview } from '../../components/ui/StoragePreview';

import { getStructuredApiError } from '../../api/errors';
import { directoryHistoryKey, filesystemApi } from '../../api/filesystem';
import { useAuth } from '../../contexts/AuthContext';
import { useDisplayPreferences } from '../../contexts/DisplayPreferencesContext';

import { useResponsive } from '../../hooks/useResponsive';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';

import type { DirectoryItem } from '../../types';

const pageSizes = [25, 50, 100];
const recentLimit = 8;

/** Keep the literal path, including spaces, and leave access checks to the server. */
function directoryParameter(params: URLSearchParams) {
  const [value, ...extras] = params.getAll('directory');
  return value?.startsWith('/') && !extras.length && !value.includes('\0') &&
    !value.split('/').some(part => part === '.' || part === '..') ? value : undefined;
}

/** Stable names and labels derive from the actual filesystem records. */
function pathName(path: string) {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

/** The directory shortcut carries the current path without starting an operation. */
function organizerLink(path: string) {
  return '/batch?' + new URLSearchParams({ operation: 'media-organize', directory: path });
}

function WorkspaceSearch({ initialValue, onSearch }: { initialValue: string; onSearch: (value: string) => void }) {
  const [draft, setDraft] = useState(initialValue);
  useEffect(() => setDraft(initialValue), [initialValue]);
  useEffect(() => setDraft(initialValue), [initialValue]);
  /** Submit explicitly so typing in a large directory does not trigger repeated scans. */
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(draft.trim());
  }
  return <form className="nfc-file-workspace-search" role="search" onSubmit={submit}>
    <ConsoleIcon name="search" size={16} />
    <input aria-label="搜索当前目录" placeholder="搜索当前目录" value={draft}
      onChange={event => setDraft(event.target.value)} />
    {draft && <button type="button" aria-label="清除搜索" onClick={() => { setDraft(''); if (initialValue) onSearch(''); }}>
      <ConsoleIcon name="x" size={15} />
    </button>}
    <ConsoleButton type="submit" size="sm" variant="ghost" disabled={draft.trim() === initialValue}>搜索</ConsoleButton>
  </form>;
}

interface WorkspaceInspectionProps {
  current: string;
  entry?: DirectoryItem;
  onOpen: (path: string) => void;
  onClose?: () => void;
  favoriteAction?: React.ReactNode;
  storageRoot?: boolean;
}

/** Inspect only server-reported paths and metadata, without inferring directory totals. */
function WorkspaceInspection({ current, entry, onOpen, onClose, favoriteAction, storageRoot }: WorkspaceInspectionProps) {
  const path = entry?.path ?? current;
  const directory = !entry || entry.type === 'directory';
  const modified = entry?.mtime_ns && Number.isFinite(entry.mtime_ns) ? new Date(entry.mtime_ns / 1e6) : null;
  return <div className="nfc-file-workspace-detail">
    <header>
      <span className="nfc-file-workspace-detail-icon"><ConsoleIcon name={directory ? 'folder' : 'file-text'} size={21} /></span>
      <div><h2>{entry?.name ?? pathName(current)}</h2><span>{directory ? '目录' : entry?.type === 'symlink' ? '链接' : '文件'}</span></div>
      {onClose && <button type="button" className="nfc-file-workspace-icon" aria-label="关闭目录详情" onClick={onClose}>
        <ConsoleIcon name="x" size={17} />
      </button>}
    </header>
    {storageRoot && <StoragePreview label={pathName(current)} />}
    {!directory && <MediaThumbnail path={path} kind="file" size="cover" />}
    <dl>
      <div><dt>位置</dt><dd><CodePath value={path} /></dd></div>
      {entry?.size != null && <div><dt>大小</dt><dd>{formatBytes(entry.size)}</dd></div>}
      {modified && Number.isFinite(modified.getTime()) && <div><dt>最近修改</dt><dd>{formatDateTime(modified.toISOString())}</dd></div>}
    </dl>
    {directory && <footer>
      <Link className="nfc-file-workspace-action" to={organizerLink(path)}>
        <ConsoleIcon name="layers" size={16} /> 预览整理
      </Link>
      {entry && <ConsoleButton onClick={() => onOpen(path)} leadingIcon={<ConsoleIcon name="folder-open" size={16} />}>打开目录</ConsoleButton>}
      {favoriteAction}
    </footer>}
  </div>;
}

/** Browse directories and retain selection, search, and pagination in browser history. */
export function FileWorkspace() {
  useTitle('文件空间');
  const [params, setParams] = useSearchParams();
  const directory = directoryParameter(params);
  const filter = params.get('search')?.trim() ?? '';
  const page = Math.max(1, Math.min(100_000, Number.parseInt(params.get('page') ?? '1', 10) || 1));
  const sizeParam = Number(params.get('size'));
  const pageSize = pageSizes.includes(sizeParam) ? sizeParam : 50;
  const selectedPath = params.get('selected');
  const overview = new URLSearchParams(params);
  overview.set('view', 'overview');
  const { isMobile, isDesktop } = useResponsive();
  const { showThumbnails } = useDisplayPreferences();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [history, setHistory] = useState<'favorites' | 'recent'>('favorites');
  const [inspectSheet, setInspectSheet] = useState<string | null>(null);
  const [inspectorClosed, setInspectorClosed] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const selectedEntry = useRef<HTMLButtonElement>(null);
  const focusNewLocation = useRef(false);
  const favoritesKey = directoryHistoryKey('favorites', user?.id);
  const recentKey = directoryHistoryKey('recent', user?.id);
  const ownerId = user?.id ?? null;
  const directoryKey = directory ?? null;
  const currentQuery = useQuery({
    queryKey: ['filesystem', 'workspace', ownerId, directoryKey, page, pageSize, filter],
    queryFn: () => filesystemApi.listDirectory(directory, false, page, pageSize, filter),
    placeholderData: (previous, previousQuery) => {
      const key = previousQuery?.queryKey;
      // Keep the paginator and scroll height for another page of the same result.
      return key?.[2] === ownerId && key[3] === directoryKey && key[6] === filter ? previous : undefined;
    },
  });
  const favorites = useQuery({ queryKey: favoritesKey, queryFn: filesystemApi.listFavorites });
  const recent = useQuery({
    queryKey: directoryHistoryKey('recent', user?.id, recentLimit),
    queryFn: () => filesystemApi.listRecent(recentLimit), enabled: history === 'recent',
  });
  const favorite = useMutation({
    mutationFn: async ({ path, existing }: { path: string; existing?: NonNullable<typeof favorites.data>['items'][number] }) => {
      if (existing) await filesystemApi.deleteFavorite(existing.id);
      else await filesystemApi.addFavorite(path);
    },
    onSettled: () => { void queryClient.invalidateQueries({ queryKey: favoritesKey }); },
  });
  const current = currentQuery.data?.path;
  const roots = currentQuery.data?.allowed_roots ?? [];
  const entries = currentQuery.data?.items ?? [];
  const selection = entries.find(item => item.path === selectedPath);
  const inspectedPath = selection?.path ?? current;
  const favoriteItem = favorites.data?.items.find(item => item.path === inspectedPath);
  const visibleHistory = history === 'favorites' ? favorites : recent;
  const currentListView = !showThumbnails || view === 'list';

  useEffect(() => {
    if (!current || !focusNewLocation.current) return;
    focusNewLocation.current = false;
    headingRef.current?.focus({ preventScroll: true });
    headingRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'instant' });
  }, [current]);

  /** Navigate only with paths provided by the backend or its directory breadcrumb. */
  function openDirectory(path: string) {
    setInspectSheet(null);
    setLocationsOpen(false);
    if (path === current && !filter && page === 1 && !selectedPath) return;
    focusNewLocation.current = path !== current;
    setInspectorClosed(false);
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.set('directory', path);
      ['search', 'page', 'selected'].forEach(key => next.delete(key));
      return next;
    });
    if (user) void filesystemApi.recordRecent([path]).then(() =>
      queryClient.invalidateQueries({ queryKey: recentKey }), () => {});
  }

  /** Selection replaces only the current history entry; opening a directory pushes a new entry. */
  function inspect(entry: DirectoryItem) {
    setInspectorClosed(false);
    setInspectSheet(entry.path);
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.set('selected', entry.path);
      return next;
    }, { replace: true });
  }

  /** Keep stale selections out of a different filtered page. */
  function changeList(search: string, nextPage: number, size: number) {
    setInspectSheet(null);
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.delete('selected');
      if (search) next.set('search', search); else next.delete('search');
      if (nextPage > 1) next.set('page', String(nextPage)); else next.delete('page');
      if (size === 50) next.delete('size'); else next.set('size', String(size));
      return next;
    });
  }

  const locations = <div className="nfc-file-workspace-locations">
    <section aria-label="允许的根目录">
      <h2>位置</h2>
      {roots.map(root => <button key={root} type="button" title={root} aria-current={current === root ? 'location' : undefined}
        onClick={() => openDirectory(root)}><ConsoleIcon name="hard-drive" size={16} /><span>{pathName(root)}</span></button>)}
    </section>
    <section aria-label="目录访问记录">
      <div className="nfc-file-workspace-segment" role="group" aria-label="目录访问来源">
        <button type="button" aria-pressed={history === 'favorites'} onClick={() => setHistory('favorites')}>收藏</button>
        <button type="button" aria-pressed={history === 'recent'} onClick={() => setHistory('recent')}>最近使用</button>
      </div>
      {visibleHistory.isPending ? <p role="status">正在读取…</p> : visibleHistory.isError ?
        <ConsoleButton size="sm" variant="ghost" onClick={() => { void visibleHistory.refetch(); }}>重试</ConsoleButton> :
        visibleHistory.data?.items.length ? visibleHistory.data.items.map(item => (
          <button key={item.path} type="button" title={item.path} disabled={!item.exists}
            aria-current={current === item.path ? 'location' : undefined}
            onClick={() => openDirectory(item.path)}>
            <ConsoleIcon name={history === 'favorites' ? 'star' : 'history'} size={15} />
            <span>{('label' in item && item.label) || pathName(item.path)}</span>
          </button>
        )) : <p>{history === 'favorites' ? '还没有收藏' : '没有最近访问'}</p>}
    </section>
    <section aria-label="文件工具">
      <h2>工作区</h2>
      <Link to={current ? organizerLink(current) : '/batch?operation=media-organize'}><ConsoleIcon name="layers" size={16} /> 整理预览</Link>
      <Link to="/directory-diff"><ConsoleIcon name="git-compare" size={16} /> 双目录对比</Link>
      <Link to="/tasks"><ConsoleIcon name="clock" size={16} /> 任务记录</Link>
    </section>
  </div>;
  const inspection = current && <WorkspaceInspection current={current} entry={selection} onOpen={openDirectory}
    storageRoot={!selection && roots.includes(current)}
    onClose={isDesktop ? () => {
      setInspectorClosed(true);
      (selectedEntry.current ?? headingRef.current)?.focus({ preventScroll: true });
    } : undefined}
    favoriteAction={inspectedPath && favorites.isSuccess && <>
      <ConsoleButton size="sm" variant="ghost" aria-pressed={Boolean(favoriteItem)} disabled={favorite.isPending}
        leadingIcon={<ConsoleIcon name="star" size={16} />}
        onClick={() => favorite.mutate({ path: inspectedPath, existing: favoriteItem })}>
        {favoriteItem ? '取消收藏' : '收藏目录'}
      </ConsoleButton>
      {favorite.isError && favorite.variables?.path === inspectedPath && <p role="alert">
        {getStructuredApiError(favorite.error).message}
      </p>}
    </>} />;

  return <section className="nfc-operations-page nfc-file-workspace" aria-label="文件空间">
    <div className={'nfc-file-workspace-panes' + (current && !inspectorClosed ? ' has-inspector' : '')}>
      {!isMobile && <aside className="nfc-file-workspace-rail">{locations}</aside>}
      <section className="nfc-file-workspace-center" aria-label="当前目录">
        <div className="nfc-file-workspace-location-bar">
          {isMobile && <ConsoleButton size="sm" variant="ghost" onClick={() => setLocationsOpen(true)}
            leadingIcon={<ConsoleIcon name="hard-drive" size={15} />}>位置</ConsoleButton>}
          {current && <PathBreadcrumb currentPath={current} allowedRoots={roots} onNavigate={openDirectory} />}
        </div>
        <div className="nfc-file-workspace-title">
          <h1 ref={headingRef} tabIndex={-1}>{current ? pathName(current) : '文件空间'}</h1>
          <div className="nfc-file-workspace-title-actions">
            {current && (!isDesktop || inspectorClosed) && <ConsoleButton size="sm" variant="ghost"
              leadingIcon={<ConsoleIcon name="info" size={16} />}
              onClick={() => { setInspectorClosed(false); setInspectSheet(inspectedPath ?? null); }}>详情</ConsoleButton>}
            <Link className="nfc-file-workspace-quiet-link" to={'/dashboard?' + overview}>
              <ConsoleIcon name="activity" size={16} /> 运行概览
            </Link>
          </div>
        </div>
        <div className="nfc-file-workspace-toolbar">
          <WorkspaceSearch key={directory ?? 'root'} initialValue={filter}
            onSearch={value => changeList(value, 1, pageSize)} />
          <ConsoleButton size="sm" variant="ghost" disabled={currentQuery.isFetching}
            leadingIcon={<ConsoleIcon name="refresh" size={16} />} onClick={() => { void currentQuery.refetch(); }}>刷新</ConsoleButton>
          <div className="nfc-file-workspace-view" role="group" aria-label="目录显示方式">
            <button type="button" aria-label="网格视图" aria-pressed={!currentListView} disabled={!showThumbnails}
              onClick={() => setView('grid')}><ConsoleIcon name="layout-dashboard" size={16} /></button>
            <button type="button" aria-label="列表视图" aria-pressed={currentListView} onClick={() => setView('list')}>
              <ConsoleIcon name="list-checks" size={16} />
            </button>
          </div>
          <ThumbnailSwitch />
        </div>
        {currentQuery.isPending ? <p className="nfc-file-workspace-loading" role="status">正在读取目录…</p> : currentQuery.isError ?
          <div className="nfc-file-workspace-error" role="alert">
            <strong>无法读取此目录</strong><p>{getStructuredApiError(currentQuery.error).message}</p>
            <ConsoleButton size="sm" onClick={() => setParams({})}>返回文件空间</ConsoleButton>
          </div> : <>
            <p className="nfc-file-workspace-count" role="status">{currentQuery.data.total.toLocaleString()} 项</p>
            {entries.length ? <ul className={'nfc-file-workspace-entries' + (currentListView ? ' is-list' : '')}
              aria-label="目录内文件" aria-busy={currentQuery.isPlaceholderData || undefined}>
              {entries.map(entry => <li key={entry.path}>
                <button type="button" title={entry.path} aria-pressed={selectedPath === entry.path}
                  disabled={currentQuery.isPlaceholderData}
                  ref={selectedPath === entry.path ? selectedEntry : undefined}
                  onClick={() => isMobile && entry.type === 'directory' ? openDirectory(entry.path) : inspect(entry)}
                  onDoubleClick={entry.type === 'directory' ? () => openDirectory(entry.path) : undefined}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && entry.type === 'directory') {
                      event.preventDefault();
                      openDirectory(entry.path);
                    }
                  }}>
                  <MediaThumbnail path={entry.path} kind={entry.type === 'directory' ? 'directory' : 'file'}
                    size={currentListView ? 'small' : 'cover'} />
                  <span className="nfc-file-workspace-entry-name"><strong>{entry.name}</strong>
                    <small>{entry.type === 'directory' ? '目录' : entry.type === 'symlink' ? '链接' :
                      entry.size != null ? formatBytes(entry.size) : '文件'}</small>
                  </span>
                  {entry.type === 'directory' && <ConsoleIcon name="chevron-right" size={15} />}
                </button>
              </li>)}
            </ul> : <ConsoleEmpty title={currentQuery.data.total ? '此页已没有项目'
              : filter ? '没有找到符合条件的项目' : '这个目录里还没有项目'}
              action={filter ? <ConsoleButton onClick={() => changeList('', 1, pageSize)}>清除搜索</ConsoleButton> : undefined} />}
            {currentQuery.data.total > 0 && <ConsolePagination page={page} pageSize={pageSize} pageSizes={pageSizes}
              total={currentQuery.data.total} onChange={(next, size) => changeList(filter, next, size)} />}
          </>}
      </section>
      {isDesktop && inspection && !inspectorClosed && <aside className="nfc-file-workspace-inspector" aria-label="目录详情">
        {inspection}
      </aside>}
    </div>
    {isMobile && locationsOpen && <ConsoleSheet open onClose={() => setLocationsOpen(false)} title="位置"
      className="nfc-file-workspace-sheet">{locations}</ConsoleSheet>}
    {!isDesktop && inspection && inspectSheet !== null && inspectSheet === inspectedPath &&
      <ConsoleSheet open onClose={() => setInspectSheet(null)} title="详情" className="nfc-file-workspace-sheet">
        {inspection}
      </ConsoleSheet>}
  </section>;
}
