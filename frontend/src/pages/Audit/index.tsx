import React, { useState } from 'react';
import { Card, Table, Typography, Tag, Button, Modal, Space, Input } from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { auditApi, dataLifecycleApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { AuditEvent } from '../../types';
import { formatAuditRetention } from '../../components/settings/data_lifecycle';

const { Title, Text } = Typography;

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

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['auditEvents', page, pageSize, searchText],
    queryFn: () => auditApi.listEvents(page, pageSize, searchText || undefined),
  });

  const columns = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '操作类型',
      dataIndex: 'operation',
      key: 'operation',
      width: 140,
      render: (op: string) => <Tag color="geekblue">{op}</Tag>,
    },
    {
      title: '影响路径',
      dataIndex: 'path',
      key: 'path',
      render: (path: string | null) => (path ? <Text code copyable>{path}</Text> : '-'),
    },
    {
      title: '执行结果',
      dataIndex: 'result',
      key: 'result',
      width: 100,
      render: (res: string) => {
        const isOk = res === 'ok' || res === 'success' || res === 'verified';
        return <Tag color={isOk ? 'success' : 'error'}>{res}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: any, record: AuditEvent) => (
        <Button size="small" type="link" onClick={() => setSelectedEvent(record)}>
          详细元数据
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Space align="center">
            <Title level={4} style={{ margin: 0 }}>
              安全审计日志
            </Title>
            {lifecyclePolicy && (
              <Tag color={lifecyclePolicy.audit_retention_days === 0 ? 'default' : 'blue'}>
                保留策略: {formatAuditRetention(lifecyclePolicy.audit_retention_days)}
              </Tag>
            )}
          </Space>
          <div>
            <Text type="secondary">按系统数据生命周期保留策略记录文件操作、隔离变更与执行校验事件</Text>
          </div>
        </div>
        <Space>
          <Input
            placeholder="搜索操作/路径..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value);
              setPage(1);
            }}
            style={{ width: 220 }}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
            刷新
          </Button>
        </Space>
      </div>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={data?.items || []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          pagination={{
            current: page,
            pageSize,
            total: data?.total || 0,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      </Card>

      <Modal
        title={`审计事件详情 #${selectedEvent?.id}`}
        open={!!selectedEvent}
        onCancel={() => setSelectedEvent(null)}
        footer={[
          <Button key="close" onClick={() => setSelectedEvent(null)}>
            关闭
          </Button>,
        ]}
        width={600}
      >
        {selectedEvent && (
          <Space direction="vertical" style={{ width: '100%', marginTop: 12 }} size="middle">
            <div>
              <Text strong>操作类型：</Text>
              <Tag color="geekblue">{selectedEvent.operation}</Tag>
            </div>
            <div>
              <Text strong>执行时间：</Text>
              <Text>{formatDateTime(selectedEvent.timestamp)}</Text>
            </div>
            <div>
              <Text strong>执行结果：</Text>
              <Tag color={selectedEvent.result === 'ok' ? 'success' : 'error'}>
                {selectedEvent.result}
              </Tag>
            </div>
            <div>
              <Text strong>涉及路径：</Text>
              <Text code copyable>{selectedEvent.path || 'N/A'}</Text>
            </div>
            <div>
              <Text strong>详细元数据 JSON：</Text>
              <pre
                style={{
                  background: 'rgba(0,0,0,0.04)',
                  padding: 12,
                  borderRadius: 8,
                  marginTop: 6,
                  maxHeight: 250,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(selectedEvent.details, null, 2)}
              </pre>
            </div>
          </Space>
        )}
      </Modal>
    </div>
  );
};
