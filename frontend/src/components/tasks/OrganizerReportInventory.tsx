import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleEmpty } from '../ui/ConsoleEmpty';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsolePagination } from '../ui/ConsolePagination';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { StatusBadge } from '../ui/StatusBadge';

import { tasksApi } from '../../api/tasks';

import { formatBytes } from '../../utils/format';

import type { OrganizerReportStatus } from '../../types/task';

const REPORT_STATUS: Record<OrganizerReportStatus, { label: string; tone: string }> = {
  retained: { label: '恢复保护', tone: 'blocked' },
  reclaimable: { label: '可回收', tone: 'ready' },
  orphan: { label: '旧报告待核对', tone: 'neutral' },
  pending: { label: '待回收', tone: 'queued' },
  released: { label: '已回收', tone: 'completed' },
  unknown: { label: '待核对', tone: 'warning' },
};

/** Open the read-only inventory and refresh it while report cleanup is pending. */
export function OrganizerReportInventory() {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data, isLoading, isError, isFetching, error, refetch } = useQuery({
    queryKey: ['organizerReports', page, pageSize],
    queryFn: () => tasksApi.getOrganizerReports(page, pageSize),
    enabled: open,
    staleTime: 0,
    refetchInterval: query => (query.state.data?.pending_count ?? 0) > 0 ? 5000 : false,
  });

  return (
    <>
      <ConsoleButton leadingIcon={<ConsoleIcon name="hard-drive" size={16} />} onClick={() => {
        setPage(1);
        setOpen(true);
      }}>整理报告盘点</ConsoleButton>
      <ConsoleSheet open={open} onClose={() => setOpen(false)}
        title="整理报告盘点" description="只读查看智能整理报告的占用、恢复保护和回收结果。">
        <div className="nfc-v2-task-inspector">
          {isLoading && <div className="nfc-overlay-loading" role="status">正在读取报告盘点…</div>}
          {isError && (
            <div className="nfc-v2-task-inline-alert" role="alert">
              <strong>报告盘点读取失败</strong>
              <p>{error?.message || '请检查任务服务连接。'}</p>
              <ConsoleButton size="sm" loading={isFetching} onClick={() => { void refetch(); }}>重试</ConsoleButton>
            </div>
          )}
          {data && (
            <>
              <section className="nfc-overlay-section">
                <header className="nfc-overlay-section-header">
                  <h3>报告占用</h3>
                  <ConsoleButton size="sm" loading={isFetching}
                    leadingIcon={<ConsoleIcon name="refresh" size={15} />}
                    onClick={() => { void refetch(); }}>刷新</ConsoleButton>
                </header>
                <dl className="nfc-v2-task-facts">
                  <div><dt>当前占用</dt><dd title={`${data.total_bytes.toLocaleString()} B`}>{formatBytes(data.total_bytes)}</dd></div>
                  <div><dt>已回收</dt><dd title={`${data.reclaimed_bytes.toLocaleString()} B`}>{formatBytes(data.reclaimed_bytes)}</dd></div>
                  <div><dt>待回收</dt><dd>{data.pending_count} 项</dd></div>
                </dl>
              </section>
              {data.items.length > 0 ? (
                <ul className="nfc-organizer-report-list" aria-label="报告清单">
                  {data.items.map(item => {
                    const badge = REPORT_STATUS[item.status] ?? REPORT_STATUS.unknown;
                    const released = item.reclaimed_bytes ?? 0;
                    return (
                      <li key={`${item.kind}:${item.job_id}`} className="nfc-overlay-section nfc-organizer-report-row">
                        <div className="nfc-organizer-report-heading">
                          <strong>{item.kind === 'preview' ? '预览报告' : '执行报告'} #{item.job_id}</strong>
                          <StatusBadge status={badge.tone} label={badge.label} />
                        </div>
                        <p>{item.reason}</p>
                        <div className="nfc-organizer-report-counts">
                          <span title={`${item.bytes.toLocaleString()} B`}>当前占用 {formatBytes(item.bytes)}</span>
                          <span>{item.files} 个文件</span>
                          {released > 0 && <span title={`${released.toLocaleString()} B`}>已回收 {formatBytes(released)}</span>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : <ConsoleEmpty title="暂无报告记录" />}
              {data.total > 0 && <ConsolePagination page={page} pageSize={pageSize} total={data.total}
                pageSizes={[20, 50, 100]} onChange={(nextPage, nextSize) => {
                  setPage(nextPage);
                  setPageSize(nextSize);
                }} />}
            </>
          )}
        </div>
      </ConsoleSheet>
    </>
  );
}
