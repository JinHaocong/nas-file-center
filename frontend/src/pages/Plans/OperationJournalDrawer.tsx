import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import type { OperationJournalEntry } from '../../types';
import { formatBytes, formatDateTime } from '../../utils/format';
import { ConsoleSheet } from '../../components/ui/ConsoleSheet';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { getStructuredApiError } from '../../api/errors';

interface Props {
  planId: number;
  open: boolean;
  onClose: () => void;
}

const beforePath = (record: OperationJournalEntry) =>
  record.before?.path || record.before?.original_path || record.before?.quarantine_path || '—';

const afterPath = (record: OperationJournalEntry) =>
  record.after?.path || record.after?.restored_path || record.after?.quarantine_path || '—';

/** All four original evidence objects are available without mutating the journal. */
const JournalEvidence: React.FC<{ record: OperationJournalEntry }> = ({ record }) => (
  <details className="nfc-v2-journal-evidence">
    <summary>查看原始审计数据</summary>
    <div className="nfc-journal-json-grid">
      {([
        ['Before JSON', record.before],
        ['After JSON', record.after],
        ['Metadata Before', record.metadata_before],
        ['Metadata After', record.metadata_after],
      ] as const).map(([label, value]) => (
        <section key={label} className="nfc-v2-journal-json">
          <h4>{label}</h4>
          <pre className="nfc-code-block">{JSON.stringify(value ?? null, null, 2)}</pre>
        </section>
      ))}
    </div>
  </details>
);

const JournalFlow: React.FC<{ record: OperationJournalEntry }> = ({ record }) => {
  const bSize = record.before?.size != null ? formatBytes(record.before.size) : null;
  const aSize = record.after?.size != null ? formatBytes(record.after.size) : null;
  const bInode = record.metadata_before?.inode;
  const aInode = record.metadata_after?.inode;
  return (
    <div className="nfc-journal-mutation">
      <div className="nfc-journal-path-flow">
        <CodePath value={beforePath(record)} />
        <ConsoleIcon name="arrow-right" size={15} />
        <CodePath value={afterPath(record)} />
      </div>
      <div className="nfc-journal-meta">
        {(bSize || aSize) && <span>大小 {bSize || '—'} → {aSize || '—'}</span>}
        {(bInode != null || aInode != null) &&
          <span>inode {bInode ?? '—'} → {aInode ?? '—'}</span>}
      </div>
    </div>
  );
};

export const OperationJournalDrawer: React.FC<Props> = ({ planId, open, onClose }) => {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, isError, error, isFetching, refetch } = useQuery({
    queryKey: ['planOperationJournal', planId, page, pageSize],
    queryFn: () => plansApi.getOperationJournal(planId, page, pageSize),
    enabled: open && !!planId,
  });

  const records = data?.items || [];
  const changePage = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };

  return (
    <ConsoleSheet
      open={open}
      onClose={onClose}
      className="nfc-v2-operation-journal"
      eyebrow="FILESYSTEM EVIDENCE"
      title={'计划 #' + planId + ' 操作日志'}
      description="Worker 真实文件系统变更的只读审计证据；Undo Plan 根据这些记录逆向生成。"
      titleAside={
        <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="refresh" size={16} />}
          loading={isFetching} onClick={() => { void refetch(); }}>刷新</ConsoleButton>
      }
    >
      <div className="nfc-overlay-stack nfc-v2-journal-body">
        <p className="nfc-overlay-intro">
          操作日志包含路径、大小、时间戳与 inode。展开记录可以查看完整的 before/after 和 metadata JSON。
        </p>
        {isError && (
          <div className="nfc-v2-journal-feedback" role="alert">
            <strong>读取操作日志失败</strong>
            <p>{getStructuredApiError(error).message || '服务端暂不可用'}</p>
            <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重试</ConsoleButton>
          </div>
        )}
        {!isError && isLoading && (
          <div className="nfc-v2-journal-feedback" role="status">正在读取操作日志…</div>
        )}
        {!isError && !isLoading && records.length === 0 && (
          <ConsoleEmpty title="当前计划暂无已完成的操作日志" />
        )}
        {!isError && !isLoading && records.length > 0 && (
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-journal-table-scroll">
                <table className="nfc-v2-journal-table">
                  <thead><tr>
                    <th scope="col">序号</th>
                    <th scope="col">操作</th>
                    <th scope="col">物理变更</th>
                    <th scope="col">执行时间</th>
                    <th scope="col">原始审计</th>
                  </tr></thead>
                  <tbody>{records.map(record => (
                    <tr key={record.id}>
                      <td className="nfc-mono">#{record.sequence}</td>
                      <td><span className="nfc-v2-journal-operation">{record.operation}</span></td>
                      <td><JournalFlow record={record} /></td>
                      <td><time dateTime={record.created_at}>{formatDateTime(record.created_at)}</time></td>
                      <td><JournalEvidence record={record} /></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            }
            mobile={
              <div className="nfc-journal-mobile-list">
                {records.map(record => (
                  <article className="nfc-journal-mobile-card" key={record.id}>
                    <div className="nfc-journal-mobile-topline">
                      <div className="nfc-v2-journal-mobile-label">
                        <span className="nfc-mono">#{record.sequence}</span>
                        <span className="nfc-v2-journal-operation">{record.operation}</span>
                      </div>
                      <time dateTime={record.created_at}>{formatDateTime(record.created_at)}</time>
                    </div>
                    <JournalFlow record={record} />
                    <JournalEvidence record={record} />
                  </article>
                ))}
              </div>
            }
          />
        )}
        {!isError && !isLoading && (data?.total ?? 0) > 0 && (
          <ConsolePagination
            page={page} pageSize={pageSize} total={data?.total ?? 0}
            pageSizes={[10, 20, 50]} onChange={changePage}
          />
        )}
      </div>
    </ConsoleSheet>
  );
};
