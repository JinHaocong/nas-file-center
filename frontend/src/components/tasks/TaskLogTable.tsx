import React, { useState } from 'react';
import { Table, Tag, Typography, Select, Space, Empty, Spin } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TaskEvent, TaskLogLevel } from '../../types/task';
import { formatDateTime } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { TASK_LOG_LEVEL_MAP } from './task_utils';

const { Text } = Typography;

interface Props {
  taskId: number;
}

export const TaskLogTable: React.FC<Props> = ({ taskId }) => {
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
      render: (val: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(val)}</Text>,
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
      render: (type: string) => <Text code style={{ fontSize: 12 }}>{type}</Text>,
    },
    {
      title: '消息内容',
      dataIndex: 'message',
      key: 'message',
      render: (msg: string) => <Text style={{ fontSize: 12 }}>{msg || '-'}</Text>,
    },
  ];

  const handleLevelChange = (val: string) => {
    setLevel(val);
    setPage(1);
  };

  return (
    <div style={{ marginTop: 12 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <Text strong style={{ fontSize: 14 }}>
          事件日志
        </Text>
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            日志级别:
          </Text>
          <Select
            size="small"
            value={level}
            onChange={handleLevelChange}
            style={{ width: 110 }}
            options={[
              { label: '全部级别', value: 'all' },
              { label: 'INFO', value: 'info' },
              { label: 'WARN', value: 'warning' },
              { label: 'ERROR', value: 'error' },
              { label: 'DEBUG', value: 'debug' },
            ]}
          />
        </Space>
      </div>

      {isError && (
        <div style={{ padding: '16px 0', textAlign: 'center' }}>
          <Text type="danger" style={{ fontSize: 12 }}>
            加载日志失败: {error instanceof Error ? error.message : '网络异常'}
          </Text>
        </div>
      )}

      <Table
        dataSource={data?.items || []}
        columns={columns}
        rowKey="id"
        size="small"
        loading={isLoading}
        expandable={{
          expandedRowKeys,
          onExpandedRowsChange: (keys) => setExpandedRowKeys(keys),
          rowExpandable: (record: TaskEvent) =>
            Boolean(record.context && Object.keys(record.context).length > 0),
          expandedRowRender: (record: TaskEvent) => {
            const sanitized = sanitizeContext(record.context);
            return (
              <pre
                style={{
                  margin: 0,
                  padding: '8px 12px',
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  fontSize: 11,
                  maxHeight: 180,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(sanitized, null, 2)}
              </pre>
            );
          },
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
        pagination={{
          current: page,
          pageSize,
          total: data?.total || 0,
          showSizeChanger: true,
          pageSizeOptions: ['20', '50', '100'],
          showTotal: (total) => `共 ${total} 条日志`,
          size: 'small',
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
    </div>
  );
};
