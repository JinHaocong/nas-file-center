import React, { useState } from 'react';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
  Switch,
  Alert,
  Descriptions,
  Input,
  message,
  Popconfirm,
  Select,
} from 'antd';
import {
  EyeOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { indexesApi } from '../../api/domain';
import { IndexRoot } from '../../types';
import { getStructuredApiError } from '../../api/errors';
import { WorkflowPreviewItem } from '../../types/workflow';

const { Text } = Typography;

interface WorkflowPreviewPanelProps {
  workflowId: number;
  revision: number;
  isDirty: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const WorkflowPreviewPanel: React.FC<WorkflowPreviewPanelProps> = ({
  workflowId,
  revision,
  isDirty,
  onGeneratePlanSuccess,
}) => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [selectedRoots, setSelectedRoots] = useState<number[] | undefined>(undefined);
  const [customPlanName, setCustomPlanName] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const { data: indexesData } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => {
      const res = await indexesApi.listIndexes(1, 100);
      return res.items;
    },
  });
  const scanRoots: IndexRoot[] = indexesData || [];

  const {
    data: preview,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['workflowPreview', workflowId, revision, page, pageSize, onlyChanged, selectedRoots],
    queryFn: () =>
      workflowApi.previewWorkflow(workflowId, {
        revision,
        page,
        page_size: pageSize,
        only_changed: onlyChanged,
        runtime_inputs: selectedRoots && selectedRoots.length > 0 ? { root_ids: selectedRoots } : undefined,
      }),
    enabled: !!workflowId && !isDirty,
  });

  const generatePlanMutation = useMutation({
    mutationFn: () => {
      if (!preview?.compile_digest) {
        throw new Error('未获取到编译摘要，无法生成计划');
      }
      return workflowApi.generatePlan(workflowId, {
        expected_compile_digest: preview.compile_digest,
        revision,
        runtime_inputs: selectedRoots && selectedRoots.length > 0 ? { root_ids: selectedRoots } : undefined,
        plan_name: customPlanName.trim() || undefined,
      });
    },
    onSuccess: (data) => {
      message.success(`批处理计划草稿 #${data.plan_id} 生成成功`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      onGeneratePlanSuccess(data.plan_id);
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      if (structured.code === 'PREVIEW_CHANGED') {
        setErrorMessage('文件状态或工作流编译摘要已发生变动，请重新刷新预览');
        refetch();
      } else if (structured.code === 'WORKFLOW_ARCHIVED') {
        setErrorMessage('工作流已被归档，禁止生成计划');
      } else {
        setErrorMessage(structured.message || '生成计划草稿失败');
      }
    },
  });

  const columns = [
    {
      title: '序号',
      key: 'index',
      width: 60,
      render: (_: any, __: any, idx: number) => (page - 1) * pageSize + idx + 1,
    },
    {
      title: '操作类型',
      dataIndex: 'operation',
      key: 'operation',
      width: 100,
      render: (op: string) => {
        const colors: Record<string, string> = {
          rename: 'cyan',
          move: 'purple',
          touch: 'blue',
          quarantine: 'orange',
        };
        return <Tag color={colors[op] || 'default'}>{op}</Tag>;
      },
    },
    {
      title: '变更状态',
      dataIndex: 'changed',
      key: 'changed',
      width: 100,
      render: (changed: boolean) =>
        changed ? <Tag color="processing">有变更</Tag> : <Tag color="default">保持/更新</Tag>,
    },
    {
      title: '源文件路径',
      dataIndex: 'source_path',
      key: 'source_path',
      ellipsis: true,
    },
    {
      title: '目标文件路径',
      dataIndex: 'target_path',
      key: 'target_path',
      ellipsis: true,
      render: (target: string | null, record: WorkflowPreviewItem) => {
        if (record.operation === 'touch') {
          return (
            <Text type="secondary">
              刷新时间戳 (mtime): {record.mtime_ns ? new Date(record.mtime_ns / 1e6).toLocaleString() : '当前时间'}
            </Text>
          );
        }
        return target || <Text type="secondary">-</Text>;
      },
    },
  ];

  return (
    <Card
      title={
        <Space>
          <EyeOutlined style={{ color: '#1677ff' }} />
          <span>执行预览与批处理计划生成 (Workflow Preview & Generate Plan)</span>
        </Space>
      }
      bordered={false}
      style={{ borderRadius: 12, marginTop: 16 }}
      extra={
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => refetch()}
            loading={isLoading}
            disabled={isDirty}
          >
            刷新预览
          </Button>

          <Popconfirm
            title="确认基于此预览生成批处理计划草稿？"
            description="计划生成为只读草稿态，仍需冻结与校验后方可执行。"
            onConfirm={() => generatePlanMutation.mutate()}
            disabled={isDirty || !preview || isLoading || generatePlanMutation.isPending}
            okText="生成草稿"
            cancelText="取消"
          >
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              disabled={isDirty || !preview || isLoading}
              loading={generatePlanMutation.isPending}
            >
              生成批处理计划草稿 (Draft)
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      {isDirty ? (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message="检测到工作流定义有未保存的变动"
          description="为保障编译与计划生成的权威性及版本一致性，系统禁止在草稿未保存状态下进行预览或生成计划。请先点击上方“保存新版本”按钮。"
          style={{ marginBottom: 16 }}
        />
      ) : (
        <>
          {errorMessage && (
            <Alert
              type="error"
              showIcon
              message="操作失败"
              description={errorMessage}
              closable
              onClose={() => setErrorMessage(null)}
              style={{ marginBottom: 16 }}
            />
          )}

          {isError && (
            <Alert
              type="error"
              showIcon
              message="工作流预览失败"
              description={getStructuredApiError(error).message}
              style={{ marginBottom: 16 }}
            />
          )}

          <div style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text type="secondary">覆盖根目录 (可选):</Text>
              <Select
                mode="multiple"
                placeholder="使用步骤预设根目录"
                value={selectedRoots}
                onChange={setSelectedRoots}
                style={{ minWidth: 220 }}
                options={(scanRoots || []).map((r) => ({
                  label: `${r.root} (ID: ${r.id})`,
                  value: r.id,
                }))}
                allowClear
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Switch
                checked={onlyChanged}
                onChange={(checked) => {
                  setOnlyChanged(checked);
                  setPage(1);
                }}
              />
              <Text type="secondary">仅显示有变更项 (过滤 touch)</Text>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
              <Input
                placeholder="自定义计划名称 (可选)"
                value={customPlanName}
                onChange={(e) => setCustomPlanName(e.target.value)}
                style={{ width: 260 }}
              />
            </div>
          </div>

          {preview && (
            <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
              <Descriptions size="small" column={3} bordered>
                <Descriptions.Item label="匹配文件/目录数">
                  <Text strong>{preview.matched_count}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="计划操作总数">
                  <Text strong style={{ color: '#1677ff' }}>
                    {preview.planned_operations_count} 项
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="预览数据源">
                  <Tag color={preview.preview_source === 'index' ? 'blue' : 'purple'}>
                    {preview.preview_source}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="编译摘要 (Compile Digest)" span={3}>
                  <Text code copyable style={{ fontSize: 12 }}>
                    {preview.compile_digest}
                  </Text>
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}

          <Table
            dataSource={preview?.items || []}
            columns={columns}
            rowKey={(r, idx) => `${r.source_path}-${r.operation}-${idx}`}
            loading={isLoading}
            size="small"
            pagination={{
              current: page,
              pageSize,
              total: preview?.planned_operations_count ?? 0,
              showSizeChanger: true,
              pageSizeOptions: ['20', '50', '100'],
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        </>
      )}
    </Card>
  );
};
