import { Fragment, useEffect, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';

import { PathBreadcrumb } from '../../components/DirectoryPicker';
import { buildDirectoryBreadcrumb } from '../../components/DirectoryPicker/path_model';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleSheet } from '../../components/ui/ConsoleSheet';
import { MediaThumbnail, ThumbnailSwitch } from '../../components/ui/MediaThumbnail';
import { StoragePreview } from '../../components/ui/StoragePreview';
import { WorkspaceEntries, workspaceEntryModified, workspaceEntryTypes } from './WorkspaceEntries';

import { getStructuredApiError } from '../../api/errors';
import { directoryHistoryKey, filesystemApi } from '../../api/filesystem';
import { useAuth } from '../../contexts/AuthContext';
import { useDisplayPreferences } from '../../contexts/DisplayPreferencesContext';

import { useResponsive } from '../../hooks/useResponsive';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes } from '../../utils/format';

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
  /** Submit explicitly so typing in a large directory does not trigger repeated scans. */
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(draft.trim());
  }
  return <form className="nfc-file-workspace-search" role="search" onSubmit={submit}>
    <ConsoleIcon name="search" size={16} />
    <input type="search" aria-label="搜索当前目录" placeholder="搜索当前目录" value={draft}
      onChange={event => setDraft(event.target.value)} />
    {draft && <button type="button" aria-label="清除搜索" onClick={() => { setDraft(''); if (initialValue) onSearch(''); }}>
      <ConsoleIcon name="x" size={15} />
    </button>}
    <button type="submit" className="nfc-file-workspace-search-submit" disabled={draft.trim() === initialValue}>搜索</button>
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
  const modified = workspaceEntryModified(entry?.mtime_ns);
  return <div className="nfc-file-workspace-detail">
    {onClose && <header className="nfc-file-workspace-inspector-bar">
      <span>{directory ? '目录详情' : '文件详情'}</span>
      <button type="button" className="nfc-file-workspace-icon" aria-label="关闭目录详情" title="收起详情" onClick={onClose}>
        <ConsoleIcon name="x" size={17} />
      </button>
    </header>}
    <div className="nfc-file-workspace-detail-body">
      <div className="nfc-file-workspace-detail-identity">
        <span className="nfc-file-workspace-detail-icon"><ConsoleIcon name={directory ? 'folder' : 'file-text'} size={20} /></span>
        <div><h2>{entry?.name ?? pathName(current)}</h2><span>{workspaceEntryTypes[entry?.type ?? 'directory']}</span></div>
      </div>
      {storageRoot && <StoragePreview label={pathName(current)} />}
      {entry && entry.type !== 'symlink' && <div className="nfc-file-workspace-detail-cover">
        <MediaThumbnail path={path} kind={directory ? 'directory' : 'file'} size="cover" />
      </div>}
      <dl>
        {entry?.size != null && <div className="nfc-file-workspace-detail-fact"><dt>大小</dt><dd>{formatBytes(entry.size)}</dd></div>}
        {modified && <div className="nfc-file-workspace-detail-fact"><dt>修改时间</dt><dd><time dateTime={modified.iso}>{modified.label}</time></dd></div>}
        <div><dt>位置</dt><dd><CodePath value={path} /></dd></div>
      </dl>
    </div>
    {directory && <footer className="nfc-file-workspace-detail-actions">
      <Link className="nfc-file-workspace-action" to={organizerLink(path)}>
        <ConsoleIcon name="layers" size={16} /> 预览整理
      </Link>
      {(entry || favoriteAction) && <div className="nfc-file-workspace-detail-secondary">
        {entry && <ConsoleButton size="sm" variant="ghost" onClick={() => onOpen(path)}
          leadingIcon={<ConsoleIcon name="folder-open" size={16} />}>打开目录</ConsoleButton>}
        {favoriteAction}
      </div>}
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
  const fileToolbar = useOutletContext<HTMLDivElement | null>();
  const { showThumbnails } = useDisplayPreferences();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [view, setView] = useState<'grid' | 'list'>('list');
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [history, setHistory] = useState<'favorites' | 'recent'>('favorites');
  const [inspectSheet, setInspectSheet] = useState<string | null>(null);
  const [inspectorClosed, setInspectorClosed] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const selectedEntry = useRef<HTMLButtonElement>(null);
  const breadcrumbRef = useRef<HTMLDivElement>(null);
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
  const currentRoot = current ? buildDirectoryBreadcrumb(current, roots)?.baseRoot : undefined;
  const entries = currentQuery.data?.items ?? [];
  const selection = entries.find(item => item.path === selectedPath);
  const inspectedPath = selection?.path ?? current;
  const showInspectionSheet = !isDesktop && inspectSheet !== null && inspectSheet === inspectedPath;
  const favoriteItem = favorites.data?.items.find(item => item.path === inspectedPath);
  const visibleHistory = history === 'favorites' ? favorites : recent;
  const currentListView = !showThumbnails || view === 'list';

  useEffect(() => {
    if (!current || !focusNewLocation.current) return;
    focusNewLocation.current = false;
    headingRef.current?.focus({ preventScroll: true });
    headingRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'instant' });
  }, [current]);

  useEffect(() => {
    const breadcrumb = breadcrumbRef.current;
    if (breadcrumb) breadcrumb.scrollLeft = breadcrumb.scrollWidth;
  }, [current, fileToolbar, isMobile]);

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
      {!isMobile && <h2>位置</h2>}
      {roots.map(root => <Fragment key={root}>
        <button type="button" title={root} aria-current={current === root ? 'location' : undefined}
          onClick={() => openDirectory(root)}><ConsoleIcon name="hard-drive" size={16} /><span>{pathName(root)}</span></button>
        {current && current !== root && currentRoot === (root.replace(/\/+$/, '') || '/') &&
          <button type="button" title={current} aria-current="location" className="nfc-file-workspace-current-location"
            onClick={() => openDirectory(current)}><ConsoleIcon name="folder" size={16} /><span>{pathName(current)}</span></button>}
      </Fragment>)}
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
            aria-current={!currentRoot && current === item.path ? 'location' : undefined}
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
      <Link to="/scans"><ConsoleIcon name="search" size={16} /> 精确去重</Link>
      <Link to="/tasks"><ConsoleIcon name="clock" size={16} /> 任务记录</Link>
      <Link className="nfc-file-workspace-overview" to={'/dashboard?' + overview}><ConsoleIcon name="activity" size={16} /> 运行概览</Link>
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

  const locationBar = <div className="nfc-file-workspace-location-bar">
    {isMobile && <ConsoleButton size="sm" variant="ghost" onClick={() => setLocationsOpen(true)}
      leadingIcon={<ConsoleIcon name="hard-drive" size={15} />}>位置</ConsoleButton>}
    <div className="nfc-file-workspace-breadcrumb" ref={breadcrumbRef}>
      {current && <PathBreadcrumb currentPath={current} allowedRoots={roots} onNavigate={openDirectory} />}
    </div>
  </div>;
  const search = <WorkspaceSearch key={directory ?? 'root'} initialValue={filter}
    onSearch={value => changeList(value, 1, pageSize)} />;
  const viewControls = <>
    <button type="button" className="nfc-file-workspace-icon" aria-label="刷新目录" title="刷新目录"
      aria-disabled={currentQuery.isFetching} aria-busy={currentQuery.isFetching || undefined}
      onClick={() => { if (!currentQuery.isFetching) void currentQuery.refetch(); }}>
      <ConsoleIcon name="refresh" size={16} />
    </button>
    <div className="nfc-file-workspace-view" role="group" aria-label="目录显示方式">
      <button type="button" aria-label="列表视图" title="列表视图" aria-pressed={currentListView} onClick={() => setView('list')}>
        <ConsoleIcon name="list-checks" size={16} />
      </button>
      <button type="button" aria-label="网格视图" title="网格视图" aria-pressed={!currentListView} disabled={!showThumbnails}
        onClick={() => setView('grid')}><ConsoleIcon name="layout-dashboard" size={16} /></button>
    </div>
  </>;
  const detailControls = <>
    <ThumbnailSwitch compact />
    {current && <button type="button" className="nfc-file-workspace-icon" aria-label={isDesktop ? '显示详情' : '详情'}
      title={isDesktop && !inspectorClosed ? '收起详情' : '显示详情'} aria-expanded={isDesktop ? !inspectorClosed : showInspectionSheet}
      onClick={() => {
        if (isDesktop) setInspectorClosed(closed => !closed);
        else setInspectSheet(inspectedPath ?? null);
      }}><ConsoleIcon name="panel-right" size={17} /></button>}
  </>;
  const toolbar = <div className="nfc-file-workspace-toolbar" role="group" aria-label="文件空间工具">
    {isMobile ? <>
      <div className="nfc-file-workspace-toolbar-line">{locationBar}<div className="nfc-file-workspace-controls">{viewControls}</div></div>
      <div className="nfc-file-workspace-toolbar-line">{search}<div className="nfc-file-workspace-controls">{detailControls}</div></div>
    </> : <>
      {locationBar}
      <div className="nfc-file-workspace-tools">{search}
        <div className="nfc-file-workspace-controls">{viewControls}{detailControls}</div>
      </div>
    </>}
  </div>;

  return <section className="nfc-operations-page nfc-file-workspace" aria-label="文件空间">
    {fileToolbar ? createPortal(toolbar, fileToolbar) : toolbar}
    <div className={'nfc-file-workspace-panes' + (current && !inspectorClosed ? ' has-inspector' : '')}>
      {!isMobile && <aside className="nfc-file-workspace-rail">{locations}</aside>}
      <section className="nfc-file-workspace-center" aria-label="当前目录">
        <div className="nfc-file-workspace-title">
          <div>
            <h1 ref={headingRef} tabIndex={-1}>{current ? pathName(current) : '文件空间'}</h1>
            {currentQuery.isSuccess && <p className="nfc-file-workspace-count" role="status">
              {filter ? '找到 ' : ''}{currentQuery.data.total.toLocaleString()} 项{selection ? ' · 已选 1 项' : ''}
            </p>}
          </div>
          {isMobile && <Link className="nfc-file-workspace-quiet-link" to={'/dashboard?' + overview}>
            <ConsoleIcon name="activity" size={16} /> 运行概览
          </Link>}
        </div>
        {currentQuery.isPending ? <p className="nfc-file-workspace-loading" role="status">正在读取目录…</p> : currentQuery.isError ?
          <div className="nfc-file-workspace-error" role="alert">
            <strong>无法读取此目录</strong><p>{getStructuredApiError(currentQuery.error).message}</p>
            <ConsoleButton size="sm" loading={currentQuery.isFetching}
              onClick={() => { void currentQuery.refetch(); }}>重试</ConsoleButton>
            {params.size > 0 && <ConsoleButton size="sm" variant="ghost" onClick={() => setParams({})}>返回文件空间</ConsoleButton>}
          </div> : <>
            {entries.length ? <WorkspaceEntries entries={entries} list={currentListView}
              selectedPath={selectedPath} selectedRef={selectedEntry} pending={currentQuery.isPlaceholderData}
              openOnClick={isMobile} onOpen={openDirectory} onInspect={inspect} /> :
              <ConsoleEmpty title={currentQuery.data.total ? '此页已没有项目'
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
    {inspection && showInspectionSheet &&
      <ConsoleSheet open onClose={() => setInspectSheet(null)} title="详情" className="nfc-file-workspace-sheet">
        {inspection}
      </ConsoleSheet>}
  </section>;
}
