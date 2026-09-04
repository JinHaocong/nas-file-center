import React, { useState } from 'react';
import { Card, Table, Button, Typography, Space, Tag, message } from 'antd';
import { ScheduleOutlined, ReloadOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';
import { PlanDeleteButton } from '../../components/plans/PlanDeleteButton';
import { PlanHistoryCleanupModal } from '../../components/plans/PlanHistoryCleanupModal';
import { LegacyPlanCleanup } from '../../components/plans/LegacyPlanCleanup';

const { Title, Text } = Typography;

export const PlansPage: React.FC = () => {
  useTitle('执行计划');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['plansList', page, pageSize],
    queryFn: () => plansApi.listPlans(page, pageSize),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some((p: any) => p.status === 'validating' || p.status === 'executing');
      return hasActive ? 3000 : false;
    },
  });

  const deletePlanMutation = useMutation({
    mutationFn: (id: number) => plansApi.deletePlan(id),
    onMutate: (id) => setDeletingId(id),
    onSuccess: (_, id) => {
      message.success(`计划 #${id} 已安全删除`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      if (data?.items?.length === 1 && page > 1) {
        setPage((prev) => prev - 1);
      }
    },
    onError: (err: any) => {
      message.error(err.message || '删除计划失败');
    },
    onSettled: () => setDeletingId(null),
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
        <Space size="small">
          <Button size="small" type="link" onClick={() => navigate(`/plans/${record.id}`)}>
            查看与执行
          </Button>
          <PlanDeleteButton
            plan={record}
            onDelete={() => deletePlanMutation.mutate(record.id)}
            loading={deletingId === record.id}
          />
        </Space>
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
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
            刷新
          </Button>
          <PlanHistoryCleanupModal />
        </Space>
      </div>

      <LegacyPlanCleanup />

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
