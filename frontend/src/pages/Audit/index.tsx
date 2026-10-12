import React, { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useQuery } from '@tanstack/react-query';
import { auditApi, dataLifecycleApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import type { AuditEvent } from '../../types';
import { formatAuditRetention } from '../../components/settings/data_lifecycle';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';

const isSuccessResult = (value: string) => ['ok', 'success', 'verified'].includes(value);

export const AuditPage: React.FC = () => {
  useTitle('审计日志');
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
  const [searchText, setSearchText] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data: lifecyclePolicy } = useQuery({
    queryKey: ['dataLifecyclePolicy'],
    queryFn: () => dataLifecycleApi.getPolicy(),
  });
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['auditEvents', page, pageSize, searchText],
    queryFn: () => auditApi.listEvents(page, pageSize, searchText || undefined),
  });

  const items = data?.items || [];
  const changePage = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };
  const renderDetailsButton = (event: AuditEvent) => (
    <ConsoleButton size="sm" variant="ghost"
      onClick={() => setSelectedEvent(event)}>详细元数据</ConsoleButton>
  );

  return (
    <div className="nfc-operations-page nfc-audit-page nfc-page-layout-ledger nfc-v2-audit-page">
      <PageHeader
        eyebrow="Forensics"
        title="审计日志"
        description="按系统数据生命周期保留策略记录文件操作、隔离变更与执行校验事件。"
        actions={<ActionBar compact>
          {lifecyclePolicy && <span className="nfc-retention-badge">
            保留 {formatAuditRetention(lifecyclePolicy.audit_retention_days)}
          </span>}
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void refetch(); }} loading={isFetching}>刷新</ConsoleButton>
        </ActionBar>}
      />
      <DataPanel title="审计事件"
        description="按操作、路径和服务端可搜索字段检索。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} events</span>}
        className="nfc-panel-flush" variant="dense">
        <ActionBar className="nfc-filter-bar nfc-v2-audit-filter">
          <label className="nfc-v2-audit-search" htmlFor="audit-search-input">
            <ConsoleIcon name="search" size={17} />
            <input id="audit-search-input" type="search" value={searchText}
              placeholder="搜索操作/路径..."
              onChange={event => { setSearchText(event.target.value); setPage(1); }} />
          </label>
        </ActionBar>
        {isError && (
          <div className="nfc-v2-audit-feedback" role="alert">
            <strong>审计事件读取失败</strong>
            <p>{getStructuredApiError(error).message || '服务端暂不可用'}</p>
            <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重试</ConsoleButton>
          </div>
        )}
        {!isError && isLoading && (
          <div className="nfc-v2-audit-feedback" role="status">正在读取审计事件…</div>
        )}
        {!isError && !isLoading && items.length === 0 && (
          <ConsoleEmpty title="暂无审计事件" description="没有符合当前筛选条件的审计记录。" />
        )}
        {!isError && !isLoading && items.length > 0 && (
          <>
            <ResponsiveDataView
              desktop={<div className="nfc-v2-audit-table-scroll">
                <table className="nfc-v2-audit-table">
                  <thead><tr>
                    <th scope="col">时间</th><th scope="col">操作类型</th>
                    <th scope="col">影响路径</th><th scope="col">结果</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(event => (
                    <tr key={event.id}>
                      <td className="nfc-table-meta">{formatDateTime(event.timestamp)}</td>
                      <td><span className="nfc-operation-badge">{event.operation}</span></td>
                      <td><CodePath value={event.path} /></td>
                      <td><StatusBadge status={isSuccessResult(event.result) ? 'completed' : 'failed'}
                        label={event.result} /></td>
                      <td>{renderDetailsButton(event)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<div className="nfc-mobile-record-list nfc-v2-audit-mobile">
                {items.map(event => (
                  <article className="nfc-audit-mobile-card" key={event.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-plan-mobile-heading-copy">
                        <span className="nfc-operation-badge">{event.operation}</span>
                        <span className="nfc-mobile-record-title nfc-mono">#{event.id}</span>
                      </div>
                      <StatusBadge status={isSuccessResult(event.result) ? 'completed' : 'failed'}
                        label={event.result} />
                    </div>
                    <div className="nfc-audit-mobile-path"><CodePath value={event.path} /></div>
                    <div className="nfc-mobile-record-meta">{formatDateTime(event.timestamp)}</div>
                    <div className="nfc-mobile-record-actions">{renderDetailsButton(event)}</div>
                  </article>
                ))}
              </div>}
            />
            <ConsolePagination page={page} pageSize={pageSize} total={data?.total || 0}
              pageSizes={[10, 20, 50, 100]} onChange={changePage} />
          </>
        )}
      </DataPanel>
      <Dialog.Root open={selectedEvent !== null}
        onOpenChange={next => { if (!next) setSelectedEvent(null); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
          <Dialog.Content className="nfc-v2-dialog nfc-overlay-modal nfc-audit-detail-modal nfc-v2-audit-detail-modal"
            onPointerDownOutside={event => event.preventDefault()}>
            <header className="nfc-v2-dialog-heading">
              <span className="nfc-v2-dialog-icon"><ConsoleIcon name="file-text" size={20} /></span>
              <div>
                <Dialog.Title>审计事件详情 #{selectedEvent?.id}</Dialog.Title>
                <Dialog.Description>原始操作与元数据记录（只读）。</Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button type="button" className="nfc-v2-dialog-close" aria-label="关闭审计详情">
                  <ConsoleIcon name="x" size={18} />
                </button>
              </Dialog.Close>
            </header>
            {selectedEvent && (
              <div className="nfc-audit-detail">
                <div><span>操作类型</span><strong className="nfc-operation-badge">{selectedEvent.operation}</strong></div>
                <div><span>执行时间</span><strong>{formatDateTime(selectedEvent.timestamp)}</strong></div>
                <div><span>执行结果</span><StatusBadge
                  status={isSuccessResult(selectedEvent.result) ? 'completed' : 'failed'}
                  label={selectedEvent.result} /></div>
                <div><span>涉及路径</span><CodePath value={selectedEvent.path} /></div>
                <div className="nfc-audit-json"><span>详细元数据 JSON</span>
                  <pre className="nfc-code-block">{JSON.stringify(selectedEvent.details, null, 2)}</pre>
                </div>
              </div>
            )}
            <div className="nfc-v2-confirm-actions">
              <ConsoleButton onClick={() => setSelectedEvent(null)}>关闭</ConsoleButton>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
};
