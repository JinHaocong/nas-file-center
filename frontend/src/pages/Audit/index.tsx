import React, { useState } from 'react';
import { Button, Empty, Input, Modal, Pagination, Table } from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { auditApi, dataLifecycleApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { AuditEvent } from '../../types';
import { formatAuditRetention } from '../../components/settings/data_lifecycle';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';

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

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['auditEvents', page, pageSize, searchText],
    queryFn: () => auditApi.listEvents(page, pageSize, searchText || undefined),
  });

  const items = data?.items || [];

  const columns = [
    { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 178, render: (v: string) => <span className="nfc-table-meta">{formatDateTime(v)}</span> },
    { title: '操作类型', dataIndex: 'operation', key: 'operation', width: 156, render: (op: string) => <span className="nfc-operation-badge">{op}</span> },
    { title: '影响路径', dataIndex: 'path', key: 'path', render: (path: string | null) => <CodePath value={path} /> },
    { title: '结果', dataIndex: 'result', key: 'result', width: 116, render: (res: string) => <StatusBadge status={isSuccessResult(res) ? 'completed' : 'failed'} label={res} /> },
    { title: '操作', key: 'action', width: 112, render: (_: unknown, record: AuditEvent) => <Button size="small" type="text" onClick={() => setSelectedEvent(record)}>详细元数据</Button> },
  ];

  return (
    <div className="nfc-operations-page">
      <PageHeader
        eyebrow="SAFETY & OPERATIONS"
        title="审计日志"
        description="按系统数据生命周期保留策略记录文件操作、隔离变更与执行校验事件。"
        actions={
          <ActionBar compact>
            {lifecyclePolicy && <span className="nfc-retention-badge">保留 {formatAuditRetention(lifecyclePolicy.audit_retention_days)}</span>}
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>刷新</Button>
          </ActionBar>
        }
      />

      <DataPanel title="审计事件" description="按操作、路径和服务端可搜索字段检索。" action={<span className="nfc-panel-count">{data?.total ?? 0} events</span>} className="nfc-panel-flush">
        <ActionBar className="nfc-filter-bar">
          <Input
            className="nfc-search-input"
            placeholder="搜索操作/路径..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setPage(1); }}
            allowClear
          />
        </ActionBar>
        <ResponsiveDataView
          desktop={<Table dataSource={items} columns={columns} rowKey="id" loading={isLoading} pagination={{ current: page, pageSize, total: data?.total || 0, showSizeChanger: true, pageSizeOptions: ['10','20','50','100'], onChange: (p,ps)=>{setPage(p);setPageSize(ps);} }} />}
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {items.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计事件" /> : items.map((event) => (
                  <article className="nfc-audit-mobile-card" key={event.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-plan-mobile-heading-copy">
                        <span className="nfc-operation-badge">{event.operation}</span>
                        <span className="nfc-mobile-record-title nfc-mono">#{event.id}</span>
                      </div>
                      <StatusBadge status={isSuccessResult(event.result) ? 'completed' : 'failed'} label={event.result} />
                    </div>
                    <div className="nfc-audit-mobile-path"><CodePath value={event.path} /></div>
                    <div className="nfc-mobile-record-meta">{formatDateTime(event.timestamp)}</div>
                    <div className="nfc-mobile-record-actions"><Button type="text" onClick={() => setSelectedEvent(event)}>详细元数据</Button></div>
                  </article>
                ))}
              </div>
              <div className="nfc-mobile-pagination"><Pagination current={page} pageSize={pageSize} total={data?.total || 0} showSizeChanger pageSizeOptions={['10','20','50','100']} onChange={(p,ps)=>{setPage(p);setPageSize(ps);}} /></div>
            </>
          }
        />
      </DataPanel>

      <Modal title={`审计事件详情 #${selectedEvent?.id}`} open={!!selectedEvent} onCancel={() => setSelectedEvent(null)} footer={<Button onClick={() => setSelectedEvent(null)}>关闭</Button>} width={680}>
        {selectedEvent && (
          <div className="nfc-audit-detail">
            <div><span>操作类型</span><strong className="nfc-operation-badge">{selectedEvent.operation}</strong></div>
            <div><span>执行时间</span><strong>{formatDateTime(selectedEvent.timestamp)}</strong></div>
            <div><span>执行结果</span><StatusBadge status={isSuccessResult(selectedEvent.result) ? 'completed' : 'failed'} label={selectedEvent.result} /></div>
            <div><span>涉及路径</span><CodePath value={selectedEvent.path} /></div>
            <div className="nfc-audit-json"><span>详细元数据 JSON</span><pre>{JSON.stringify(selectedEvent.details, null, 2)}</pre></div>
          </div>
        )}
      </Modal>
    </div>
  );
};
