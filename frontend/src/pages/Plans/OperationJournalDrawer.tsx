import React, { useState } from 'react';
import {
  Button,
  Descriptions,
  Drawer,
  Empty,
  Pagination,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowRightOutlined,
  HistoryOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import { OperationJournalEntry } from '../../types';
import { formatBytes, formatDateTime } from '../../utils/format';
import { useResponsive } from '../../hooks/useResponsive';

const { Text, Paragraph } = Typography;

interface Props {
  planId: number;
  open: boolean;
  onClose: () => void;
}

const OP_COLORS: Record<string, string> = {
  rename: 'cyan',
  move: 'purple',
  quarantine: 'orange',
  restore: 'green',
  touch: 'blue',
  delete: 'red',
};

const beforePath = (record: OperationJournalEntry) =>
  record.before?.path || record.before?.original_path || record.before?.quarantine_path || '—';

const afterPath = (record: OperationJournalEntry) =>
  record.after?.path || record.after?.restored_path || record.after?.quarantine_path || '—';

export const OperationJournalDrawer: React.FC<Props> = ({ planId, open, onClose }) => {
  const { isMobile } = useResponsive();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['planOperationJournal', planId, page, pageSize],
    queryFn: () => plansApi.getOperationJournal(planId, page, pageSize),
    enabled: open && !!planId,
  });

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 70,
      render: (seq: number) => <Text strong>#{seq}</Text>,
    },
    {
      title: '操作',
      dataIndex: 'operation',
      key: 'operation',
      width: 100,
      render: (op: string) => <Tag color={OP_COLORS[op] || 'default'}>{op}</Tag>,
    },
    {
      title: '物理变更',
      key: 'mutation_details',
      render: (_: unknown, record: OperationJournalEntry) => {
        const bSize = record.before?.size != null ? formatBytes(record.before.size) : null;
        const aSize = record.after?.size != null ? formatBytes(record.after.size) : null;
        const bInode = record.metadata_before?.inode;
        const aInode = record.metadata_after?.inode;

        return (
          <div className="nfc-journal-mutation">
            <div className="nfc-journal-path-flow">
              <Text code>{beforePath(record)}</Text>
              <ArrowRightOutlined />
              <Text code>{afterPath(record)}</Text>
            </div>
            <div className="nfc-journal-meta">
              {(bSize || aSize) && <span>大小 {bSize || '—'} → {aSize || '—'}</span>}
              {(bInode || aInode) && <span>inode {bInode || '—'} → {aInode || '—'}</span>}
            </div>
          </div>
        );
      },
    },
    {
      title: '执行时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (val: string) => formatDateTime(val),
    },
  ];

  const records = data?.items || [];

  return (
    <Drawer
      rootClassName="nfc-overlay-drawer nfc-operation-journal-drawer"
      title={
        <div className="nfc-drawer-title">
          <span className="nfc-drawer-title-kicker">Filesystem evidence</span>
          <div className="nfc-drawer-title-row">
            <HistoryOutlined />
            <span>计划 #{planId} 操作日志</span>
          </div>
        </div>
      }
      placement="right"
      width={900}
      open={open}
      onClose={onClose}
      extra={
        <Button icon={<ReloadOutlined />} size="small" onClick={() => refetch()} loading={isLoading}>
          刷新
        </Button>
      }
    >
      <div className="nfc-overlay-stack">
        <section className="nfc-overlay-section">
          <Paragraph type="secondary" className="nfc-overlay-intro">
            Operation Journal 是 Worker 对真实文件系统变更的审计证据，包含路径、大小、时间戳与 inode；Undo Plan 会基于这些记录逆向生成。
          </Paragraph>
        </section>

        <section className="nfc-overlay-section nfc-overlay-section-flush">
          {isMobile ? (
            <div className="nfc-journal-mobile-list">
              {records.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="当前计划暂无已完成的操作日志"
                />
              ) : (
                records.map((record: OperationJournalEntry) => (
                  <article className="nfc-journal-mobile-card" key={record.id}>
                    <div className="nfc-journal-mobile-topline">
                      <div>
                        <span className="nfc-mono">#{record.sequence}</span>
                        <Tag color={OP_COLORS[record.operation] || 'default'}>{record.operation}</Tag>
                      </div>
                      <time>{formatDateTime(record.created_at)}</time>
                    </div>
                    <div className="nfc-journal-mobile-flow">
                      <Text code>{beforePath(record)}</Text>
                      <ArrowRightOutlined />
                      <Text code>{afterPath(record)}</Text>
                    </div>
                    <details className="nfc-log-context">
                      <summary>查看原始审计数据</summary>
                      <div className="nfc-journal-json-grid">
                        <pre className="nfc-code-block">{JSON.stringify(record.before, null, 2)}</pre>
                        <pre className="nfc-code-block">{JSON.stringify(record.after, null, 2)}</pre>
                        <pre className="nfc-code-block">{JSON.stringify(record.metadata_before, null, 2)}</pre>
                        <pre className="nfc-code-block">{JSON.stringify(record.metadata_after, null, 2)}</pre>
                      </div>
                    </details>
                  </article>
                ))
              )}
            </div>
          ) : (
            <Table
              className="nfc-embedded-table"
              dataSource={records}
              columns={columns}
              rowKey="id"
              loading={isLoading}
              size="middle"
              pagination={false}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="当前计划暂无已完成的操作日志"
                  />
                ),
              }}
              expandable={{
                expandedRowRender: (record) => (
                  <Descriptions className="nfc-journal-expanded" size="small" column={2}>
                    <Descriptions.Item label="Before JSON" span={2}>
                      <pre className="nfc-code-block">{JSON.stringify(record.before, null, 2)}</pre>
                    </Descriptions.Item>
                    <Descriptions.Item label="After JSON" span={2}>
                      <pre className="nfc-code-block">{JSON.stringify(record.after, null, 2)}</pre>
                    </Descriptions.Item>
                    <Descriptions.Item label="Metadata Before">
                      <pre className="nfc-code-block">{JSON.stringify(record.metadata_before, null, 2)}</pre>
                    </Descriptions.Item>
                    <Descriptions.Item label="Metadata After">
                      <pre className="nfc-code-block">{JSON.stringify(record.metadata_after, null, 2)}</pre>
                    </Descriptions.Item>
                  </Descriptions>
                ),
              }}
            />
          )}

          {records.length > 0 && (
            <Pagination
              className="nfc-embedded-pagination"
              current={page}
              pageSize={pageSize}
              total={data?.total || 0}
              showSizeChanger={!isMobile}
              pageSizeOptions={['10', '20', '50']}
              simple={isMobile}
              onChange={(p, ps) => {
                setPage(p);
                setPageSize(ps);
              }}
            />
          )}
        </section>
      </div>
    </Drawer>
  );
};
