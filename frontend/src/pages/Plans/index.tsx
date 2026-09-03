import React, { useState } from 'react';
import { Card, Table, Button, Typography, Space, Tag } from 'antd';
import { ScheduleOutlined, ReloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';

const { Title, Text } = Typography;

export const PlansPage: React.FC = () => {
  useTitle('执行计划');
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['plansList', page, pageSize],
    queryFn: () => plansApi.listPlans(page, pageSize),
  });

  const columns = [
    {
      title: '计划名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: any) => (
        <Space>
          <ScheduleOutlined style={{ color: '#1677ff' }} />
          <a onClick={() => navigate(`/plans/${record.id}`)} style={{ fontWeight: 600 }}>
            {text}
          </a>
        </Space>
      ),
    },
    {
      title: '计划类型',
      dataIndex: 'kind',
      key: 'kind',
      render: (kind: string) => <Tag color="geekblue">{kind}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const item = STATUS_MAP[status] || { label: status, color: 'default' };
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: '变更文件项数',
      dataIndex: 'expected_changes',
      key: 'expected_changes',
      render: (val: number) => `${val.toLocaleString()} 项`,
    },
    {
      title: '预计可释放容量',
      dataIndex: 'expected_reclaim_bytes',
      key: 'expected_reclaim_bytes',
      render: (bytes: number) => (
        <Text type={bytes > 0 ? 'success' : undefined} strong={bytes > 0}>
          {formatBytes(bytes)}
        </Text>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: any) => (
        <Button size="small" type="link" onClick={() => navigate(`/plans/${record.id}`)}>
          查看与执行
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            执行计划管理
          </Title>
          <Text type="secondary">
            所有文件操作均严格遵循 Dry Run 计划生命周期：Draft → Frozen → Validate → Execute
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
          刷新
        </Button>
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
    </div>
  );
};
