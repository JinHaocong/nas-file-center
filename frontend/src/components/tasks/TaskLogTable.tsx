import React, { useState } from 'react';
import { Empty, Pagination, Select, Spin, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TaskEvent, TaskLogLevel } from '../../types/task';
import { formatDateTime } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { useResponsive } from '../../hooks/useResponsive';
import { TASK_LOG_LEVEL_MAP } from './task_utils';

const { Text } = Typography;

interface Props {
  taskId: number;
}

export const TaskLogTable: React.FC<Props> = ({ taskId }) => {
  const { isMobile } = useResponsive();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [level, setLevel] = useState<string>('all');
  const [expandedRowKeys, setExpandedRowKeys] = useState<readonly React.Key[]>([]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['taskLogs', taskId, page, pageSize, level],
    queryFn: () =>
      tasksApi.getTaskLogs(taskId, {
        page,
        pageSize,
        level: level === 'all' ? undefined : level,
      }),
  });

  const columns = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 170,
      render: (val: string) => <Text className="nfc-table-secondary">{formatDateTime(val)}</Text>,
    },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 90,
      render: (lvl: TaskLogLevel) => {
        const config = TASK_LOG_LEVEL_MAP[lvl] || { color: 'default', label: lvl };
        return <Tag color={config.color}>{config.label}</Tag>;
      },
    },
    {
      title: '事件类型',
      dataIndex: 'event_type',
      key: 'event_type',
      width: 140,
      render: (type: string) => <Text code>{type}</Text>,
    },
    {
      title: '消息内容',
      dataIndex: 'message',
      key: 'message',
      render: (msg: string) => <Text>{msg || '-'}</Text>,
    },
  ];

  const handleLevelChange = (val: string) => {
    setLevel(val);
    setPage(1);
  };

  const items = data?.items || [];

  const pagination = (
    <Pagination
      className="nfc-embedded-pagination"
      current={page}
      pageSize={pageSize}
      total={data?.total || 0}
      showSizeChanger={!isMobile}
      pageSizeOptions={['20', '50', '100']}
      showTotal={isMobile ? undefined : (total) => `共 ${total} 条日志`}
      size="small"
      simple={isMobile}
      onChange={(p, ps) => {
        setPage(p);
        setPageSize(ps);
      }}
    />
  );

  return (
    <section className="nfc-task-log-panel">
      <header className="nfc-embedded-section-header">
        <div>
          <div className="nfc-embedded-section-kicker">Event stream</div>
          <h3>事件日志</h3>
        </div>
        <label className="nfc-inline-filter">
          <span>级别</span>
          <Select
            size="small"
            value={level}
            onChange={handleLevelChange}
            options={[
              { label: '全部级别', value: 'all' },
              { label: 'INFO', value: 'info' },
              { label: 'WARN', value: 'warning' },
              { label: 'ERROR', value: 'error' },
              { label: 'DEBUG', value: 'debug' },
            ]}
          />
        </label>
      </header>

      {isError && (
        <div className="nfc-inline-error">
          加载日志失败: {error instanceof Error ? error.message : '网络异常'}
        </div>
      )}

      {isMobile ? (
        <div className="nfc-task-log-mobile-list">
          {isLoading ? (
            <div className="nfc-overlay-loading"><Spin size="small" /></div>
          ) : items.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={level === 'all' ? '暂无事件日志' : '当前级别无匹配日志'}
            />
          ) : (
            items.map((record: TaskEvent) => {
              const config = TASK_LOG_LEVEL_MAP[record.level] || { color: 'default', label: record.level };
              const context = sanitizeContext(record.context);
              const hasContext = Boolean(context && Object.keys(context).length > 0);
              return (
                <article className="nfc-task-log-mobile-card" key={record.id}>
                  <div className="nfc-task-log-mobile-topline">
                    <Tag color={config.color}>{config.label}</Tag>
                    <time>{formatDateTime(record.timestamp)}</time>
                  </div>
                  <div className="nfc-task-log-mobile-event">{record.event_type}</div>
                  <p>{record.message || '—'}</p>
                  {hasContext && (
                    <details className="nfc-log-context">
                      <summary>查看上下文</summary>
                      <pre className="nfc-code-block">
                        {JSON.stringify(context, null, 2)}
                      </pre>
                    </details>
                  )}
                </article>
              );
            })
          )}
          {items.length > 0 && pagination}
        </div>
      ) : (
        <>
          <Table
            className="nfc-embedded-table"
            dataSource={items}
            columns={columns}
            rowKey="id"
            size="small"
            loading={isLoading}
            expandable={{
              expandedRowKeys,
              onExpandedRowsChange: (keys) => setExpandedRowKeys(keys),
              rowExpandable: (record: TaskEvent) =>
                Boolean(record.context && Object.keys(record.context).length > 0),
              expandedRowRender: (record: TaskEvent) => (
                <pre className="nfc-code-block">
                  {JSON.stringify(sanitizeContext(record.context), null, 2)}
                </pre>
              ),
            }}
            locale={{
              emptyText: isLoading ? (
                <Spin size="small" />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={level === 'all' ? '暂无事件日志' : '当前级别无匹配日志'}
                />
              ),
            }}
            pagination={false}
          />
          {items.length > 0 && pagination}
        </>
      )}
    </section>
  );
};
