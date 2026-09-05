import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Alert,
  Spin,
  Tooltip,
  message,
  Popconfirm,
} from 'antd';
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  LockOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { plansApi, settingsApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';
import { PlanItem } from '../../types';
import { PlanDeleteButton } from '../../components/plans/PlanDeleteButton';
import {
  invalidatePlanDeleteFailure,
  getPlanDetailRenderState,
  getPlanDetailView,
} from '../../components/plans/plan_cleanup';

const { Title, Text } = Typography;

export const PlanDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const planId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useTitle(`计划详情 #${planId}`);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
  });

  const {
    data: plan,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['planDetail', planId, page, pageSize],
    queryFn: () => plansApi.getPlanDetail(planId, page, pageSize),
  });

  const freezeMutation = useMutation({
    mutationFn: () => plansApi.freezePlan(planId),
    onSuccess: () => {
      message.success('计划已成功冻结，参数已不可篡改');
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
    },
    onError: (err: any) => {
      message.error(err.message || '冻结失败');
    },
  });

  const validateMutation = useMutation({
    mutationFn: () => plansApi.validatePlan(planId),
    onSuccess: () => {
      message.success('计划校验完成，状态已就绪 (Ready)');
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
    },
    onError: (err: any) => {
      message.error(err.message || '校验失败');
    },
  });

  const executeMutation = useMutation({
    mutationFn: () => plansApi.executePlan(planId),
    onSuccess: (data) => {
      message.success(`计划已加入任务队列，任务 #${data.work_job_id}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      queryClient.invalidateQueries({ queryKey: ['workJobs'] });
    },
    onError: (err: any) => {
      message.error(err.message || '执行失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => plansApi.deletePlan(planId),
    onSuccess: () => {
      message.success(`计划 #${planId} 已安全删除`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      navigate('/plans');
    },
    onError: (err: any) => {
      message.error(err.message || '删除计划失败');
      invalidatePlanDeleteFailure(queryClient, planId);
    },
  });

  const renderState = getPlanDetailRenderState({
    isLoading,
    isError,
    error,
    hasPlan: !!plan,
  });

  const view = getPlanDetailView(renderState, !!plan);

  if (view === 'loading') {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (view === 'not-found') {
    return (
      <Alert
        message="计划不存在"
        description={`未找到 ID 为 #${planId} 的批处理计划`}
        type="error"
        showIcon
        action={<Button onClick={() => navigate('/plans')}>返回计划列表</Button>}
      />
    );
  }

  if (view === 'error') {
    return (
      <Alert
        message="加载计划失败"
        description={(error as any)?.message || '获取计划详情失败，请检查网络或稍后重试'}
        type="error"
        showIcon
        action={<Button onClick={() => refetch()}>重试</Button>}
      />
    );
  }

  if (!plan) {
    return (
      <Alert
        message="计划不存在"
        description={`未找到 ID 为 #${planId} 的批处理计划`}
        type="error"
        showIcon
        action={<Button onClick={() => navigate('/plans')}>返回计划列表</Button>}
      />
    );
  }

  const isSafeMode = !settings?.allow_mutation;
  const hasActiveJob = Boolean(plan.active_work_job_id);
  const executeDisabled = isSafeMode || hasActiveJob;
  const statusConfig = STATUS_MAP[plan.status] || { label: plan.status, color: 'default' };

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 70,
      render: (seq: number) => <Text strong>#{seq}</Text>,
    },
    {
      title: '操作类型',
      dataIndex: 'operation',
      key: 'operation',
      width: 110,
      render: (op: string) => {
        const colors: Record<string, string> = {
          quarantine: 'orange',
          touch: 'blue',
          move: 'purple',
          rename: 'cyan',
          delete: 'red',
        };
        return <Tag color={colors[op] || 'default'}>{op}</Tag>;
      },
    },
    {
      title: '源文件 / 待操作路径',
      dataIndex: 'source',
      key: 'source',
      render: (text: string) => (
        <Text code copyable>
          {text}
        </Text>
      ),
    },
    {
      title: '目标路径 / 保留副本',
      key: 'target_or_keep',
      render: (_: any, record: PlanItem) => {
        if (record.target) {
          return (
            <Space>
              <ArrowRightOutlined style={{ color: '#1677ff' }} />
              <Text code copyable style={{ color: '#1677ff' }}>
                {record.target}
              </Text>
            </Space>
          );
        }
        if (record.keep) {
          return (
            <Space>
              <Tag color="green">保留首选</Tag>
              <Text code copyable>
                {record.keep}
              </Text>
            </Space>
          );
        }
        return '-';
      },
    },
    {
      title: '预估容量',
      dataIndex: 'expected_size',
      key: 'expected_size',
      width: 110,
      render: (bytes: number) => (bytes > 0 ? formatBytes(bytes) : '-'),
    },
    {
      title: '校验状态',
      dataIndex: 'state',
      key: 'state',
      width: 100,
      render: (state: string) => {
        const item = STATUS_MAP[state] || { label: state, color: 'default' };
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: '执行备注',
      dataIndex: 'reason',
      key: 'reason',
      render: (reason: string) => reason || '-',
    },
  ];

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
        }}
      >
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/plans')}>
            返回列表
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            计划详情: {plan.name}
          </Title>
          <Tag color={statusConfig.color} style={{ fontSize: 13, padding: '2px 8px' }}>
            {statusConfig.label}
          </Tag>
        </Space>

        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
            刷新
          </Button>

          {plan.status === 'draft' && (
            <Button
              icon={<LockOutlined />}
              onClick={() => freezeMutation.mutate()}
              loading={freezeMutation.isPending}
            >
              冻结计划 (Freeze)
            </Button>
          )}

          {(plan.status === 'frozen' || plan.status === 'ready' || plan.status === 'partial') && (
            <Tooltip
              title={
                hasActiveJob
                  ? `该计划当前已有执行任务进行中 (任务 #${plan.active_work_job_id})`
                  : undefined
              }
            >
              <span>
                <Button
                  type="primary"
                  ghost
                  icon={<CheckCircleOutlined />}
                  onClick={() => validateMutation.mutate()}
                  loading={validateMutation.isPending}
                  disabled={hasActiveJob}
                >
                  SHA256 实时校验 (Validate)
                </Button>
              </span>
            </Tooltip>
          )}

          {(plan.status === 'ready' || plan.status === 'partial') && (
            <Tooltip
              title={
                isSafeMode
                  ? '当前处于只读安全模式 (ALLOW_MUTATION=false)，执行按钮已被锁定。若确认执行，请修改 compose 环境变量开启允许写入。'
                  : hasActiveJob
                    ? `该计划当前已有执行任务进行中 (任务 #${plan.active_work_job_id})`
                    : '执行计划：将按计划安全变更/隔离文件'
              }
            >
              <span>
                <Popconfirm
                  title="确认执行计划？"
                  description="请确认您已仔细核对所有计划项并完成了校验。"
                  onConfirm={() => executeMutation.mutate()}
                  disabled={executeDisabled}
                  okText="确认执行"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button
                    type="primary"
                    danger
                    icon={<PlayCircleOutlined />}
                    disabled={executeDisabled}
                    loading={executeMutation.isPending}
                  >
                    执行计划 (Execute)
                  </Button>
                </Popconfirm>
              </span>
            </Tooltip>
          )}

          <PlanDeleteButton
            plan={plan}
            onDelete={() => deleteMutation.mutate()}
            loading={deleteMutation.isPending}
            type="default"
            size="middle"
          />
        </Space>
      </div>

      {isSafeMode && (
        <Alert
          message="只读安全保护模式生效中"
          description="系统当前以 ALLOW_MUTATION=false 运行。您可以安全进行 Dry Run 计划生成与 SHA256 校验，但无法直接触发 Execute 执行。"
          type="info"
          showIcon
          icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Descriptions bordered column={{ xs: 1, sm: 2, md: 3 }}>
          <Descriptions.Item label="计划 ID">#{plan.id}</Descriptions.Item>
          <Descriptions.Item label="计划类型">
            <Tag color="geekblue">{plan.kind}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatDateTime(plan.created_at)}</Descriptions.Item>
          <Descriptions.Item label="预计变更项数">
            <Text strong style={{ fontSize: 16 }}>
              {plan.expected_changes} 项
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="预计可释放容量">
            <Text strong style={{ fontSize: 16, color: '#52c41a' }}>
              {formatBytes(plan.expected_reclaim_bytes)}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="冻结时间">
            {plan.frozen_at ? formatDateTime(plan.frozen_at) : <Text type="secondary">未冻结</Text>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={`计划项清单 (共 ${plan.total_items ?? plan.expected_changes} 项)`}
        bordered={false}
        style={{ borderRadius: 12 }}
      >
        <Table
          dataSource={plan.items || []}
          columns={columns}
          rowKey={(r) => r.id || `${r.source}_${r.sequence}`}
          pagination={{
            current: page,
            pageSize,
            total: plan.total_items ?? plan.expected_changes,
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100', '200'],
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
