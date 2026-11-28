import { useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';

import { getStructuredApiError } from '../../api/errors';
import { mediaOrganizerBatchApi, type MediaCurrentEntry, type OrganizerJobId } from '../../api/mediaOrganizerBatch';

interface Scope {
  previewId: OrganizerJobId;
  unit: string;
  cursor: string;
}

const pageSize = 25;

/** Request only a visible directory and leave old results out of its new page. */
function useCurrentDirectory(scope: Scope, directory: string, page: number, active: boolean) {
  const query = useQuery({
    queryKey: ['mediaOrganizerCurrentEntries', scope.previewId, scope.unit, scope.cursor, directory, page],
    queryFn: () => mediaOrganizerBatchApi.getCurrentEntries(scope.previewId, scope.unit, scope.cursor, directory, page, pageSize),
    enabled: active,
    refetchOnWindowFocus: false,
    staleTime: 1000,
    retry: false,
  });
  const result = query.data;
  return { ...query, data: result?.unit === scope.unit && result.directory === directory && result.page === page ? result : undefined };
}

type CurrentDirectoryQuery = ReturnType<typeof useCurrentDirectory>;

/** Keep the tree inline while opening a branch, with each expansion scoped to its exact directory. */
function CurrentEntry({ scope, entry }: { scope: Scope; entry: MediaCurrentEntry }) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const id = useId();
  const directory = entry.type === 'directory';
  const query = useCurrentDirectory(scope, entry.path, page, directory && open);
  if (!directory) {
    return <li className="nfc-organizer-current-file">
      <ConsoleIcon name={entry.kind === 'image' ? 'image' : entry.kind === 'video' ? 'play' : 'file-text'} size={14} />
      <span>{entry.name}</span>
    </li>;
  }

  return <li className="nfc-organizer-current-folder">
    <button type="button" className="nfc-organizer-current-trigger" aria-expanded={open} aria-controls={open ? id : undefined}
      aria-label={`${open ? '收起' : '展开'} ${entry.name}`} onClick={() => setOpen(previous => !previous)}>
      <ConsoleIcon name={open ? 'folder-open' : 'folder'} size={14} />
      <span>{entry.name + '/'}</span>
      {query.data && <small>{query.data.total.toLocaleString()} 项</small>}
      <ConsoleIcon className="nfc-organizer-current-chevron" name="chevron-down" size={13} />
    </button>
    {open && <div id={id} className="nfc-organizer-current-branch">
      <CurrentDirectory scope={scope} directory={entry.path} query={query} page={page} onPage={setPage} />
    </div>}
  </li>;
}

/** Render validated response entries in the order returned by the live directory listing. */
function CurrentDirectory({ scope, directory, query, page, onPage }: {
  scope: Scope; directory: string; query: CurrentDirectoryQuery; page: number; onPage: (page: number) => void;
}) {
  if (query.isError) return <div className="nfc-organizer-current-message" role="alert">
    <span>{getStructuredApiError(query.error).message || '无法读取当前目录'}</span>
    <ConsoleButton size="sm" onClick={() => { void query.refetch(); }}>重试</ConsoleButton>
  </div>;
  if (query.isPending) return <p className="nfc-organizer-current-message" role="status">正在读取当前目录…</p>;
  const data = query.data;
  if (!data) return <p className="nfc-organizer-current-message" role="status">当前目录信息不可用</p>;
  const prefix = directory.endsWith('/') ? directory : directory + '/';
  const items = data.items.filter(entry => entry.name && !entry.name.includes('/') &&
    !['.', '..'].includes(entry.name) && entry.path === prefix + entry.name);
  return <>
    {items.length > 0 ? <ul className="nfc-organizer-current-entries" aria-label="当前目录内容">
      {items.map(entry => <CurrentEntry key={entry.path} scope={scope} entry={entry} />)}
    </ul> : <p className="nfc-organizer-current-message">目录为空</p>}
    {data.total > pageSize && <ConsolePagination page={page} pageSize={pageSize} total={data.total}
      pageSizes={[pageSize]} onChange={onPage} />}
  </>;
}

/** An already organized unit displays its live layout and needs no proposed mapping. */
export function OrganizerCurrentStructure({ previewId, unit, cursor }: {
  previewId: OrganizerJobId; unit: string; cursor?: string;
}) {
  const [page, setPage] = useState(1);
  const scope = { previewId, unit, cursor: cursor ?? '' };
  const supported = cursor !== undefined && /^\d+$/.test(cursor);
  const query = useCurrentDirectory(scope, unit, page, supported);
  return <>
    <div className="nfc-organizer-current-path">
      <ConsoleIcon name="folder-open" size={15} />
      <CodePath value={unit} />
    </div>
    <section className="nfc-organizer-current-structure" aria-label="已整理目录结构">
      <header>
        <h4>目录结构</h4>
        {query.data && <span>{query.data.total.toLocaleString()} 项</span>}
      </header>
      <div className="nfc-organizer-current-tree">
        <h5><ConsoleIcon name="arrow-right" size={14} /> 整理后</h5>
        <div className="nfc-organizer-current-root"><ConsoleIcon name="folder-open" size={15} />{unit.split('/').filter(Boolean).at(-1) ?? unit}</div>
        {supported ? <CurrentDirectory scope={scope} directory={unit} query={query} page={page} onPage={setPage} />
          : <p className="nfc-organizer-current-message">重新扫描后可在此查看当前目录结构。</p>}
      </div>
      {query.data && <p className="nfc-organizer-structure-note">从当前目录读取</p>}
    </section>
  </>;
}
