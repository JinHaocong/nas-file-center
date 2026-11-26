import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useQuery } from '@tanstack/react-query';
import { downloadVerificationApi } from '../../api/downloadVerification';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';

interface Props {
  open: boolean;
  sourceId: number | null;
  sourceName: string;
  initialPath: string;
  onClose: () => void;
  onConfirm: (path: string) => void;
  returnFocusTo?: HTMLElement | null;
}

export const RemoteDirectoryPicker: React.FC<Props> = ({
  open, sourceId, sourceName, initialPath, onClose, onConfirm, returnFocusTo,
}) => {
  const [path, setPath] = useState('');
  const [search, setSearch] = useState('');
  const locationRow = useRef<HTMLDivElement>(null);
  const pendingLocationFocus = useRef<{ path: string; opener: Element | null } | null>(null);
  useEffect(() => {
    if (open) {
      setPath(initialPath.replace(/^\/+|\/+$/g, ''));
      setSearch('');
      pendingLocationFocus.current = null;
    }
  }, [open, sourceId, initialPath]);

  const browse = useQuery({
    queryKey: ['download-verify-source-directory', sourceId, path],
    queryFn: () => downloadVerificationApi.browse(sourceId!, path),
    enabled: open && sourceId !== null,
    retry: false,
    staleTime: 5000,
  });
  const data = browse.data?.path === path ? browse.data : null;
  const ready = Boolean(open && sourceId !== null && data && !browse.isFetching && !browse.isError);
  const children = useMemo(() => (data?.items || []).filter(entry =>
    entry.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())), [data, search]);
  const segments = path ? path.split('/') : [];

  useEffect(() => {
    const pending = pendingLocationFocus.current;
    if (!pending) return;
    if (!open || sourceId === null || path !== pending.path || browse.isError) {
      pendingLocationFocus.current = null;
      return;
    }
    if (browse.isFetching || !browse.data) return;
    pendingLocationFocus.current = null;
    if (!ready) return;

    const active = document.activeElement;
    if (active === document.body || (active === pending.opener && active instanceof HTMLElement &&
        !active.isContentEditable && !active.matches('input, textarea, select, [role="textbox"]'))) {
      locationRow.current?.focus({ preventScroll: true });
    }
  }, [open, sourceId, path, browse.isError, browse.isFetching, browse.data, ready]);

  /** Move focus to the new directory context after a successful read. */
  const navigate = (next: string) => {
    if (next !== path) pendingLocationFocus.current = { path: next, opener: document.activeElement };
    setPath(next);
    setSearch('');
  };
  const confirm = () => {
    // Never choose a stale/unreadable remote directory.
    if (ready) {
      onConfirm(path);
      onClose();
    }
  };

  return (
    <Dialog.Root open={open && sourceId !== null} onOpenChange={next => { if (!next) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-directory-overlay" />
        <Dialog.Content className="nfc-directory-picker-modal nfc-overlay-modal nfc-v2-directory-dialog nfc-dv-remote-dialog nfc-reading-picker"
          onPointerDownOutside={event => event.preventDefault()}
          onCloseAutoFocus={event => {
            if (returnFocusTo?.isConnected && !returnFocusTo.matches(':disabled')) {
              event.preventDefault();
              returnFocusTo.focus();
            }
          }}>
          <header className="nfc-v2-directory-dialog-header">
            <div className="nfc-directory-picker-title">
              <ConsoleIcon name="folder-open" size={20} />
              <div>
                <Dialog.Title>选择来源目录</Dialog.Title>
                <Dialog.Description>在 {sourceName} 中选择文件夹。浏览时仅列出目录成员。</Dialog.Description>
              </div>
            </div>
            <button type="button" className="nfc-v2-directory-close"
              aria-label="关闭来源目录选择" onClick={onClose}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>

          <div className="nfc-directory-picker-body">
            <div className="nfc-directory-browser-toolbar">
              <div ref={locationRow} tabIndex={-1} role="group" aria-label="当前来源位置" className="nfc-directory-browser-row">
                <nav className="nfc-v2-path-breadcrumb nfc-dv-remote-breadcrumb" aria-label="来源目录位置">
                  <button type="button" className="nfc-v2-breadcrumb-link"
                    onClick={() => navigate('')}><ConsoleIcon name="folder" size={15} /> 根目录</button>
                  {segments.map((segment, i) => (
                    <React.Fragment key={segments.slice(0, i + 1).join('/')}>
                      <ConsoleIcon name="chevron-right" size={14} />
                      {i === segments.length - 1
                        ? <span aria-current="location">{segment}</span>
                        : <button type="button" className="nfc-v2-breadcrumb-link"
                            onClick={() => navigate(segments.slice(0, i + 1).join('/'))}>{segment}</button>}
                    </React.Fragment>
                  ))}
                </nav>
                <div className="nfc-v2-directory-toolbar-actions">
                  <ConsoleButton size="sm" disabled={!path} leadingIcon={<ConsoleIcon name="arrow-up" size={15} />}
                    onClick={() => navigate(segments.slice(0, -1).join('/'))}>上一级</ConsoleButton>
                  <ConsoleButton size="sm" disabled={browse.isFetching}
                    leadingIcon={<ConsoleIcon name="refresh" size={15} />}
                    onClick={() => { void browse.refetch(); }}>刷新</ConsoleButton>
                </div>
              </div>
            </div>
            <div className="nfc-v2-directory-panel">
              <div className="nfc-directory-search-row">
                <ConsoleIcon name="search" size={15} />
                <input aria-label="搜索来源目录" type="search" value={search}
                  onChange={event => setSearch(event.target.value)} placeholder="筛选当前目录中的文件夹或文件" />
              </div>
              <div className="nfc-directory-list-viewport" aria-busy={browse.isFetching || undefined}>
                {browse.isFetching && <p className="nfc-v2-directory-loading" role="status">正在读取目录…</p>}
                {browse.isError && <div className="nfc-v2-directory-error" role="alert">
                  <ConsoleIcon name="info" size={17} />
                  无法读取目录，请检查来源地址、服务账号权限和网络连接。
                </div>}
                {ready && children.length === 0 && <ConsoleEmpty title={search ? '没有匹配项目' : '此目录为空'}
                  description={search ? undefined : '可以选择当前目录。'}
                  action={search ? <ConsoleButton size="sm" onClick={() => setSearch('')}>清除筛选</ConsoleButton> : undefined} />}
                {ready && children.length > 0 && <ul className="nfc-v2-directory-list">
                  {children.map(entry => (
                    <li key={entry.name}>
                      {entry.kind === 'directory' ? (
                        <button type="button" className="nfc-v2-directory-open"
                          onClick={() => navigate(path ? path + '/' + entry.name : entry.name)}>
                          <ConsoleIcon name="folder" size={17} />
                          <span><strong>{entry.name}</strong></span>
                          <ConsoleIcon name="chevron-right" size={15} />
                        </button>
                      ) : (
                        <div className="nfc-dv-remote-file">
                          <ConsoleIcon name="file-text" size={17} />
                          <span>{entry.name}</span><small>文件</small>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>}
              </div>
            </div>
          </div>

          <footer className="nfc-directory-picker-footer">
            <div className="nfc-directory-picker-selection">
              <small>当前来源路径</small>
              <strong className="nfc-dv-remote-current">{'/' + path}</strong>
            </div>
            <div className="nfc-directory-picker-footer-actions">
              <ConsoleButton onClick={onClose}>取消</ConsoleButton>
              <ConsoleButton variant="primary" disabled={!ready} onClick={confirm}>选择此目录</ConsoleButton>
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
