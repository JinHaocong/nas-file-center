import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { filesystemApi } from '../../api/filesystem';
import { DirectoryPickerModalProps } from './types';
import { PathBreadcrumb } from './PathBreadcrumb';
import { formatDateTime } from '../../utils/format';
import { useResponsive } from '../../hooks/useResponsive';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleEmpty } from '../ui/ConsoleEmpty';
import { ConsolePagination } from '../ui/ConsolePagination';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../ui/ConsoleToast';
import {
  initialDirectorySelection, isWithinDirectoryRoots,
  resolveDirectorySelection, toggleDirectorySelection,
} from './selection_model';

type Tab = 'browser' | 'favorites' | 'recent';
const PAGE_SIZE = 100;

export const DirectoryPickerModal: React.FC<DirectoryPickerModalProps> = ({
  open, onCancel, onConfirm, multiple = false, initialPath, selectedValues,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const { isMobile } = useResponsive();
  const [currentPath, setCurrentPath] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [favoriteLabel, setFavoriteLabel] = useState('');
  const [isAddingFavorite, setIsAddingFavorite] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('browser');
  const [confirmFavoriteId, setConfirmFavoriteId] = useState<number | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const confirmingRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    const initial = initialDirectorySelection(selectedValues, multiple);
    setSelectedPaths(initial);
    setCurrentPath(initialPath?.trim() || initial[0] || '');
    setSearchQuery('');
    setPage(1);
    setIsAddingFavorite(false);
    setFavoriteLabel('');
    setActiveTab('browser');
    setConfirmFavoriteId(null);
    setIsConfirming(false);
    confirmingRef.current = false;
  }, [open, initialPath, selectedValues, multiple]);

  const { data: dirData, isLoading: isDirLoading, isFetching: isDirFetching,
    isError: isDirError, error: dirError, refetch: refetchDir,
  } = useQuery({
    queryKey: ['filesystem', 'list', currentPath, page, PAGE_SIZE, searchQuery],
    queryFn: () => filesystemApi.listDirectory(
      currentPath || undefined, true, page, PAGE_SIZE, searchQuery || undefined,
    ),
    enabled: open,
    staleTime: 5000,
  });
  useEffect(() => {
    if (open && dirData?.path && !currentPath) setCurrentPath(dirData.path);
  }, [open, dirData?.path, currentPath]);

  const { data: favData, isError: isFavError, refetch: refetchFav } = useQuery({
    queryKey: ['filesystem', 'favorites'],
    queryFn: () => filesystemApi.listFavorites(),
    enabled: open,
    staleTime: 10000,
  });
  const { data: recentData, isError: isRecentError, refetch: refetchRecent } = useQuery({
    queryKey: ['filesystem', 'recent'],
    queryFn: () => filesystemApi.listRecent(20),
    enabled: open,
    staleTime: 10000,
  });

  const addFavMutation = useMutation({
    mutationFn: ({ path, label }: { path: string; label?: string }) =>
      filesystemApi.addFavorite(path, label),
    onSuccess: () => {
      toast.success('已添加到收藏');
      setIsAddingFavorite(false);
      setFavoriteLabel('');
      queryClient.invalidateQueries({ queryKey: ['filesystem', 'favorites'] });
    },
    onError: (err: Error) => toast.error(err.message || '添加收藏失败'),
  });
  const delFavMutation = useMutation({
    mutationFn: (id: number) => filesystemApi.deleteFavorite(id),
    onSuccess: () => {
      toast.success('已删除收藏');
      setConfirmFavoriteId(null);
      queryClient.invalidateQueries({ queryKey: ['filesystem', 'favorites'] });
    },
    onError: (err: Error) => toast.error(err.message || '删除收藏失败'),
  });

  // Show only a backend-resolved current directory; never use stale list data
  // when navigating to a different path or switching pages/search terms.
  const resolvedPath = dirData?.path || '';
  const effectiveCurrentPath =
    !isDirError && !isDirFetching && dirData &&
    (!currentPath || resolvedPath === currentPath) ? resolvedPath : '';
  const allowedRoots = dirData?.allowed_roots || [];
  const isCurrentAllowed = isWithinDirectoryRoots(effectiveCurrentPath, allowedRoots);
  const isCurrentFavorite = useMemo(() =>
    favData?.items?.some(item => item.path === effectiveCurrentPath),
  [favData?.items, effectiveCurrentPath]);

  const handleNavigate = (path: string) => {
    if (confirmingRef.current) return;
    setCurrentPath(path);
    setSearchQuery('');
    setPage(1);
    setActiveTab('browser');
  };
  const handleToggleSelect = (path: string) => {
    if (confirmingRef.current || !isWithinDirectoryRoots(path, allowedRoots)) return;
    setSelectedPaths(previous => toggleDirectorySelection(previous, path, multiple));
  };
  const handleSelectCurrent = () => {
    if (!isCurrentAllowed || confirmingRef.current) return;
    setSelectedPaths(previous => multiple
      ? (previous.includes(effectiveCurrentPath) ? previous : [...previous, effectiveCurrentPath])
      : [effectiveCurrentPath]);
  };
  const cancel = () => {
    if (confirmingRef.current || addFavMutation.isPending || delFavMutation.isPending) return;
    onCancel();
  };
  const handleConfirm = async () => {
    if (confirmingRef.current || isDirFetching || isDirError || !dirData) return;
    const selection = resolveDirectorySelection(selectedPaths, effectiveCurrentPath, multiple);
    if (!selection) return;
    const paths = Array.isArray(selection) ? selection : [selection];
    if (!paths.every(path => isWithinDirectoryRoots(path, allowedRoots))) {
      toast.error('选择包含白名单范围外的路径；请重新选择允许的目录');
      return;
    }
    confirmingRef.current = true;
    setIsConfirming(true);
    try {
      // Recents recording is best-effort and must never make selected paths
      // mutate or turn a valid selection into an unsafe fallback.
      await filesystemApi.recordRecent(paths).catch(() => {});
      onConfirm(selection);
      onCancel();
    } finally {
      confirmingRef.current = false;
      setIsConfirming(false);
    }
  };
  const busy = isConfirming || addFavMutation.isPending || delFavMutation.isPending;
  const hasSelection = selectedPaths.length > 0 || isCurrentAllowed;

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) cancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-directory-overlay" />
        <Dialog.Content
          className="nfc-directory-picker-modal nfc-overlay-modal nfc-v2-directory-dialog"
          data-mobile={isMobile || undefined}
          onEscapeKeyDown={event => { if (busy || confirmFavoriteId !== null) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}
          aria-describedby="nfc-v2-directory-description"
        >
          <header className="nfc-v2-directory-dialog-header">
            <div className="nfc-directory-picker-title">
              <ConsoleIcon name="folder-open" size={19} />
              <div>
                <Dialog.Title>选择目录 ({multiple ? '多选' : '单选'})</Dialog.Title>
                <Dialog.Description id="nfc-v2-directory-description">
                  仅能选择服务器 ALLOWED_ROOTS 允许的目录；最终由后端校验路径。
                </Dialog.Description>
              </div>
            </div>
            <button type="button" className="nfc-v2-directory-close"
              disabled={busy} onClick={cancel} aria-label="关闭目录选择">
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>

          <div className="nfc-directory-picker-body">
            <div className="nfc-directory-browser-toolbar">
              <div className="nfc-directory-browser-row">
                <PathBreadcrumb currentPath={effectiveCurrentPath}
                  allowedRoots={allowedRoots} onNavigate={handleNavigate} />
                <div className="nfc-v2-directory-toolbar-actions">
                  <ConsoleButton size="sm" disabled={busy || !dirData?.parent}
                    leadingIcon={<ConsoleIcon name="arrow-up" size={15} />}
                    aria-label="返回上一级"
                    onClick={() => dirData?.parent && handleNavigate(dirData.parent)}>
                    上一级
                  </ConsoleButton>
                  <ConsoleButton size="sm" disabled={busy} loading={isDirFetching}
                    aria-label="刷新目录" onClick={() => { void refetchDir(); }}
                    leadingIcon={<ConsoleIcon name="refresh" size={15} />}>刷新</ConsoleButton>
                  <ConsoleButton size="sm" disabled={busy || !isCurrentAllowed}
                    aria-label="收藏当前目录"
                    leadingIcon={<ConsoleIcon name="star" size={15} />}
                    onClick={() => setIsAddingFavorite(previous => !previous)}>
                    {isCurrentFavorite ? '已收藏' : '收藏'}
                  </ConsoleButton>
                  <ConsoleButton size="sm" disabled={busy || !isCurrentAllowed}
                    leadingIcon={<ConsoleIcon name="plus" size={15} />}
                    onClick={handleSelectCurrent}>选择当前目录</ConsoleButton>
                </div>
              </div>
              {isAddingFavorite && isCurrentAllowed && (
                <div className="nfc-directory-favorite-editor">
                  <input type="text" aria-label="收藏别名" value={favoriteLabel}
                    placeholder="收藏别名（可选）"
                    disabled={busy}
                    onChange={event => setFavoriteLabel(event.target.value)} />
                  <ConsoleButton size="sm" variant="primary" loading={addFavMutation.isPending}
                    disabled={busy || !!isCurrentFavorite}
                    onClick={() => addFavMutation.mutate({
                      path: effectiveCurrentPath, label: favoriteLabel,
                    })}>保存收藏</ConsoleButton>
                  <ConsoleButton size="sm" disabled={busy}
                    onClick={() => setIsAddingFavorite(false)}>取消</ConsoleButton>
                </div>
              )}
            </div>

            <div className="nfc-v2-directory-tabs" role="tablist" aria-label="目录来源">
              {([
                ['browser', '目录浏览', 'folder'],
                ['favorites', '收藏目录 (' + (favData?.items?.length || 0) + ')', 'star'],
                ['recent', '最近使用 (' + (recentData?.items?.length || 0) + ')', 'history'],
              ] as const).map(([tab, label, icon]) => (
                <button type="button" role="tab" key={tab} id={'nfc-directory-tab-' + tab}
                  aria-selected={activeTab === tab} aria-controls={'nfc-directory-panel-' + tab}
                  disabled={busy} className={activeTab === tab ? 'is-active' : ''}
                  onClick={() => setActiveTab(tab)}>
                  <ConsoleIcon name={icon} size={15} />{label}
                </button>
              ))}
            </div>
            <div role="tabpanel" id={'nfc-directory-panel-' + activeTab}
              aria-labelledby={'nfc-directory-tab-' + activeTab}
              className="nfc-v2-directory-panel">
              {activeTab === 'browser' && (
                <>
                  <div className="nfc-directory-search-row">
                    <ConsoleIcon name="search" size={17} />
                    <input type="search" aria-label="搜索子目录"
                      placeholder="搜索子目录（如 Download、Photos）..."
                      value={searchQuery} disabled={busy}
                      onChange={event => { setSearchQuery(event.target.value); setPage(1); }} />
                  </div>
                  {isDirError ? (
                    <div className="nfc-v2-directory-error" role="alert">
                      无法读取目录：{dirError instanceof Error ? dirError.message : '请检查目录访问权限'}
                      <ConsoleButton size="sm" onClick={() => { void refetchDir(); }}>重试</ConsoleButton>
                    </div>
                  ) : isDirLoading || isDirFetching ? (
                    <p className="nfc-v2-directory-loading" role="status">正在读取目录…</p>
                  ) : !dirData?.items?.length ? (
                    <ConsoleEmpty title={searchQuery ? '没有匹配的子目录' : '当前目录下无子文件夹'} />
                  ) : (
                    <>
                      <div className="nfc-directory-list-viewport">
                        <ul className="nfc-v2-directory-list">
                          {dirData.items.map(item => (
                            <li className={selectedPaths.includes(item.path) ? 'is-selected' : ''}
                              key={item.path}>
                              <button type="button" className="nfc-v2-directory-open"
                                disabled={busy} onClick={() => handleNavigate(item.path)}
                                aria-label={'进入目录 ' + item.name}>
                                <ConsoleIcon name="folder" size={18} />
                                <span><strong>{item.name}</strong><small>{item.path}</small></span>
                              </button>
                              {multiple ? (
                                <label className="nfc-v2-directory-toggle">
                                  <input type="checkbox" aria-label={'选择目录 ' + item.name}
                                    disabled={busy} checked={selectedPaths.includes(item.path)}
                                    onChange={() => handleToggleSelect(item.path)} />
                                </label>
                              ) : (
                                <ConsoleButton size="sm"
                                  variant={selectedPaths.includes(item.path) ? 'primary' : 'secondary'}
                                  disabled={busy} onClick={() => handleToggleSelect(item.path)}>
                                  {selectedPaths.includes(item.path) ? '已选' : '选择'}
                                </ConsoleButton>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div className="nfc-directory-pagination-row">
                        <span>共 {dirData.total} 个目录</span>
                        {dirData.total > PAGE_SIZE && (
                          <ConsolePagination page={page} pageSize={PAGE_SIZE}
                            total={dirData.total} pageSizes={[PAGE_SIZE]}
                            onChange={newPage => setPage(newPage)} />
                        )}
                      </div>
                    </>
                  )}
                </>
              )}
              {activeTab === 'favorites' && (
                <div className="nfc-directory-secondary-list">
                  {isFavError ? (
                    <div className="nfc-v2-directory-error" role="alert">
                      收藏目录加载失败
                      <ConsoleButton size="sm" onClick={() => { void refetchFav(); }}>重试</ConsoleButton>
                    </div>
                  ) : !favData?.items?.length ? (
                    <ConsoleEmpty title="暂无收藏目录" description="可在目录浏览中收藏常用路径" />
                  ) : (
                    <ul className="nfc-v2-directory-list">
                      {favData.items.map(fav => (
                        <li className={fav.exists ? '' : 'is-missing'} key={fav.id}>
                          <ConsoleIcon name="star" size={18} />
                          <div className="nfc-v2-directory-item-copy">
                            <strong>{fav.label || fav.path}</strong>
                            <small>{fav.path}{!fav.exists && ' · 路径不存在'}</small>
                          </div>
                          <ConsoleButton size="sm" disabled={!fav.exists || busy}
                            onClick={() => handleNavigate(fav.path)}>进入目录</ConsoleButton>
                          <ConsoleButton size="sm" variant="danger" disabled={busy}
                            aria-label={'删除收藏 ' + (fav.label || fav.path)}
                            onClick={() => setConfirmFavoriteId(fav.id)}
                            leadingIcon={<ConsoleIcon name="trash" size={14} />}>删除</ConsoleButton>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {activeTab === 'recent' && (
                <div className="nfc-directory-secondary-list">
                  {isRecentError ? (
                    <div className="nfc-v2-directory-error" role="alert">
                      最近访问目录加载失败
                      <ConsoleButton size="sm" onClick={() => { void refetchRecent(); }}>重试</ConsoleButton>
                    </div>
                  ) : !recentData?.items?.length ? (
                    <ConsoleEmpty title="暂无最近使用记录" />
                  ) : (
                    <ul className="nfc-v2-directory-list">
                      {recentData.items.map(rec => (
                        <li className={rec.exists ? '' : 'is-missing'} key={rec.id}>
                          <ConsoleIcon name="history" size={18} />
                          <div className="nfc-v2-directory-item-copy">
                            <strong>{rec.path}</strong>
                            <small>最近使用时间：{formatDateTime(rec.last_used_at)}
                              {!rec.exists && ' · 路径不存在'}
                            </small>
                          </div>
                          <ConsoleButton size="sm" disabled={!rec.exists || busy}
                            onClick={() => handleNavigate(rec.path)}>进入目录</ConsoleButton>
                          {multiple ? (
                            <label className="nfc-v2-directory-toggle">
                              <input type="checkbox" aria-label={'选择最近目录 ' + rec.path}
                                disabled={!rec.exists || busy}
                                checked={selectedPaths.includes(rec.path)}
                                onChange={() => handleToggleSelect(rec.path)} />
                            </label>
                          ) : (
                            <ConsoleButton size="sm" disabled={!rec.exists || busy}
                              onClick={() => handleToggleSelect(rec.path)}>
                              {selectedPaths.includes(rec.path) ? '已选' : '选择'}
                            </ConsoleButton>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>

          <footer className="nfc-directory-picker-footer">
            <div className="nfc-directory-picker-selection">
              {multiple ? (
                <>
                  <span>已选 <strong>{selectedPaths.length}</strong> 个目录</span>
                  <div className="nfc-directory-picker-selected-tags">
                    {selectedPaths.map(path => (
                      <button type="button" key={path}
                        aria-label={'移除已选目录 ' + path}
                        disabled={busy}
                        onClick={() => setSelectedPaths(previous => previous.filter(item => item !== path))}>
                        {path} <ConsoleIcon name="x" size={13} />
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <span className="nfc-directory-picker-current-selection">
                  当前选择：{selectedPaths[0] || effectiveCurrentPath || '尚未选择'}
                </span>
              )}
            </div>
            <div className="nfc-directory-picker-footer-actions">
              <ConsoleButton disabled={busy} onClick={cancel}>取消</ConsoleButton>
              <ConsoleButton variant="primary" loading={isConfirming}
                disabled={busy || isDirFetching || isDirError || !dirData || !hasSelection}
                leadingIcon={<ConsoleIcon name="check-circle" size={16} />}
                onClick={() => { void handleConfirm(); }}>确认选择</ConsoleButton>
            </div>
          </footer>
          <ConsoleConfirmDialog open={confirmFavoriteId !== null}
            onOpenChange={next => { if (!next && !delFavMutation.isPending) setConfirmFavoriteId(null); }}
            title="确认删除收藏目录？"
            description="仅删除收藏记录，不会删除 NAS 上的目录或文件。"
            confirmText="删除收藏" busy={delFavMutation.isPending}
            onConfirm={() => {
              if (confirmFavoriteId !== null && !delFavMutation.isPending) {
                delFavMutation.mutate(confirmFavoriteId);
              }
            }} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
