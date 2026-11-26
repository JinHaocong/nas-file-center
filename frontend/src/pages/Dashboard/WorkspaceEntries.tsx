import type { RefObject } from 'react';

import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { MediaThumbnail } from '../../components/ui/MediaThumbnail';
import { formatBytes, formatDateTime } from '../../utils/format';

import type { DirectoryItem } from '../../types';

export const workspaceEntryTypes = { directory: '目录', file: '文件', symlink: '链接' } as const;

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
  onOpen: (path: string) => void;
  onInspect: (entry: DirectoryItem) => void;
}

/** Use the same selection and directory navigation semantics in both presentation modes. */
export function WorkspaceEntries({ entries, list, pending, selectedPath, selectedRef, openOnClick,
  onOpen, onInspect }: WorkspaceEntriesProps) {
  const groups = [
    { label: '目录', rows: entries.filter(entry => entry.type === 'directory') },
    { label: '文件', rows: entries.filter(entry => entry.type !== 'directory') },
  ].filter(group => group.rows.length);

  return <div className={'nfc-file-workspace-entries' + (list ? ' is-list' : '')} aria-busy={pending || undefined}>
    {groups.map(({ label, rows }, index) => <section key={label} aria-label={label}>
      <h2 className="nfc-file-workspace-group-title">{label}<span>{rows.length.toLocaleString()} 项</span></h2>
      {list && index === 0 && <div className="nfc-file-workspace-column-head" aria-hidden="true">
        <span>名称</span><span>类型</span><span>大小</span><span>修改时间</span>
      </div>}
      <ul className="nfc-file-workspace-group-list" aria-label={label + '列表'}>
        {rows.map(entry => {
          const directory = entry.type === 'directory';
          const selected = selectedPath === entry.path;
          const modified = workspaceEntryModified(entry.mtime_ns);
          const size = entry.size == null ? undefined : formatBytes(entry.size);
          return <li key={entry.path}>
            <button type="button" title={entry.path} aria-pressed={selected}
              disabled={pending} ref={selected ? selectedRef : undefined}
              onClick={() => openOnClick && directory ? onOpen(entry.path) : onInspect(entry)}
              onDoubleClick={directory ? () => onOpen(entry.path) : undefined}
              onKeyDown={event => {
                if (event.key === 'Enter' && directory) {
                  event.preventDefault();
                  onOpen(entry.path);
                }
              }}>
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
              {directory && <ConsoleIcon className="nfc-file-workspace-entry-open" name="chevron-right" size={15} />}
            </button>
          </li>;
        })}
      </ul>
    </section>)}
  </div>;
}
