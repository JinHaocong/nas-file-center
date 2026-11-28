import type { KeyboardEvent, RefObject } from 'react';

import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { MediaThumbnail, mediaThumbnailKind } from '../../components/ui/MediaThumbnail';
import { formatBytes, formatDateTime } from '../../utils/format';

import type { DirectoryItem } from '../../types';

export const workspaceEntryTypes = { directory: '目录', file: '文件', symlink: '链接' } as const;

/** Keep column labels and their geometry across the directory request. */
export function WorkspaceColumnHeading() {
  return <div className="nfc-file-workspace-column-head" aria-hidden="true">
    <span>名称</span><span>类型</span><span>大小</span><span>修改时间</span>
  </div>;
}

/** Present fixed-size placeholders while there is no matching listing to display. */
export function WorkspaceEntriesLoading({ list }: { list: boolean }) {
  return <div className={'nfc-file-workspace-entries nfc-file-workspace-skeleton' + (list ? ' is-list' : '')} aria-hidden="true">
    {list && <WorkspaceColumnHeading />}
    <div className="nfc-file-workspace-placeholder-rows">
      {[48, 34, 58, 45, 37, 54, 42, 51].map((width, index) => (
        <div key={index} className="nfc-file-workspace-placeholder-row">
          <span><i /><b style={{ inlineSize: width + '%' }} /></span>
          {list && <><i /><i /><i /><span /></>}
        </div>
      ))}
    </div>
  </div>;
}

/** Preview regular media files through the same endpoint as their existing thumbnails. */
export function canQuickLook(entry: DirectoryItem) {
  return entry.type === 'file' && Boolean(mediaThumbnailKind(entry.path));
}

/** Format the server mtime in local time, keeping missing values distinct from real dates. */
export function workspaceEntryModified(mtime?: number) {
  if (!mtime || !Number.isFinite(mtime)) return undefined;
  const date = new Date(mtime / 1e6);
  if (!Number.isFinite(date.getTime())) return undefined;
  const iso = date.toISOString();
  return { iso, label: formatDateTime(iso) };
}

interface WorkspaceEntriesProps {
  entries: DirectoryItem[];
  list: boolean;
  pending: boolean;
  selectedPath: string | null;
  selectedRef: RefObject<HTMLButtonElement>;
  openOnClick: boolean;
  quickLookEnabled: boolean;
  onOpen: (path: string) => void;
  onSelect: (entry: DirectoryItem) => void;
  onInspect: (entry: DirectoryItem, trigger?: HTMLButtonElement) => void;
  onQuickLook: (entry: DirectoryItem, trigger?: HTMLButtonElement) => void;
}

/** Use the same selection and directory navigation semantics in both presentation modes. */
export function WorkspaceEntries({ entries, list, pending, selectedPath, selectedRef, openOnClick,
  quickLookEnabled, onOpen, onSelect, onInspect, onQuickLook }: WorkspaceEntriesProps) {
  const groups = [
    { label: '目录', rows: entries.filter(entry => entry.type === 'directory') },
    { label: '文件', rows: entries.filter(entry => entry.type !== 'directory') },
  ].filter(group => group.rows.length);
  const orderedEntries = groups.flatMap(group => group.rows);

  /** Arrow keys follow the rendered order, including the boundary between folders and files. */
  function browseRows(event: KeyboardEvent<HTMLButtonElement>, entry: DirectoryItem) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key === 'Enter' && entry.type === 'directory') {
      event.preventDefault();
      onOpen(entry.path);
    } else if (event.key === ' ' && quickLookEnabled && canQuickLook(entry)) {
      event.preventDefault();
      onQuickLook(entry, event.currentTarget);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const offset = event.key === 'ArrowDown' ? 1 : -1;
      const next = orderedEntries[orderedEntries.indexOf(entry) + offset];
      if (!next) return;
      const rows = event.currentTarget.closest('.nfc-file-workspace-entries')
        ?.querySelectorAll<HTMLButtonElement>('button[data-workspace-entry]');
      const target = Array.from(rows ?? []).find(row => row.dataset.workspaceEntry === next.path);
      if (!target || target.disabled) return;
      onSelect(next);
      target.focus({ preventScroll: true });
      target.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
    }
  }

  return <div className={'nfc-file-workspace-entries' + (list ? ' is-list' : '')} aria-busy={pending || undefined}>
    {list && <WorkspaceColumnHeading />}
    {groups.map(({ label, rows }) => <section key={label} aria-label={label}>
      <h2 className="nfc-file-workspace-group-title">{label}<span>{rows.length.toLocaleString()} 项</span></h2>
      <ul className="nfc-file-workspace-group-list" aria-label={label + '列表'}>
        {rows.map(entry => {
          const directory = entry.type === 'directory';
          const selected = selectedPath === entry.path;
          const modified = workspaceEntryModified(entry.mtime_ns);
          const size = entry.size == null ? undefined : formatBytes(entry.size);
          return <li key={entry.path}>
            <button type="button" title={entry.path} aria-pressed={selected} data-kind={entry.type}
              data-workspace-entry={entry.path}
              aria-keyshortcuts={quickLookEnabled && canQuickLook(entry) ? 'Space' : undefined}
              disabled={pending} ref={selected ? selectedRef : undefined}
              onClick={event => {
                if (openOnClick && directory) onOpen(entry.path);
                else if (openOnClick && quickLookEnabled && canQuickLook(entry)) onQuickLook(entry, event.currentTarget);
                else onInspect(entry, event?.currentTarget);
              }}
              onDoubleClick={directory ? () => onOpen(entry.path) : undefined}
              onKeyDown={event => browseRows(event, entry)}>
              <span className="nfc-file-workspace-entry-name">
                <MediaThumbnail path={entry.path} kind={directory ? 'directory' : 'file'} size={list ? 'small' : 'cover'} />
                <span><strong>{entry.name}</strong><small>{size ?? workspaceEntryTypes[entry.type]}</small></span>
              </span>
              {list && <>
                <span className="nfc-file-workspace-entry-kind">{workspaceEntryTypes[entry.type]}</span>
                <span className="nfc-file-workspace-entry-size">{size ?? '—'}</span>
                <span className="nfc-file-workspace-entry-time">{modified ?
                  <time dateTime={modified.iso} title={modified.label}>{modified.label.slice(0, 16)}</time> : '—'}</span>
              </>}
              {(directory || (openOnClick && quickLookEnabled && canQuickLook(entry))) &&
                <ConsoleIcon className="nfc-file-workspace-entry-open" name="chevron-right" size={15} />}
            </button>
          </li>;
        })}
      </ul>
    </section>)}
  </div>;
}
