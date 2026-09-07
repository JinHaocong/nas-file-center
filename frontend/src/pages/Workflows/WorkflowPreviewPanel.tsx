import React, { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
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
import { WorkflowPreviewItem, WorkflowPreviewResponse } from '../../types/workflow';
import { WorkflowPreviewState, transitionPreviewState } from '../../utils/workflowPreviewMachine';
import { canPreviewWorkflow, canGenerateDraft } from '../../utils/workflowRbac';
import { normalizeSelectedRoots } from '../../utils/rootCardinality';
import { computePreviewRowIndex } from '../../utils/workflowRevisionParser';

const { Text } = Typography;

export interface PreviewRequestParams {
  page: number;
  pageSize: number;
}

interface WorkflowPreviewPanelProps {
  workflowId: number;
  revision: number;
  mode?: 'file' | 'organizer';
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const WorkflowPreviewPanel: React.FC<WorkflowPreviewPanelProps> = ({
  workflowId,
  revision,
  mode = 'file',
  isDirty,
  isArchived = false,
  onGeneratePlanSuccess,
}) => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [selectedRoots, setSelectedRoots] = useState<number[] | undefined>(undefined);
  const [customPlanName, setCustomPlanName] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const isOrganizer = mode === 'organizer';

  const [previewState, setPreviewState] = useState<WorkflowPreviewState>(
    isDirty ? 'EDITING_DIRTY' : 'SAVED_PREVIEW_REQUIRED'
  );
  const [previewData, setPreviewData] = useState<WorkflowPreviewResponse | null>(null);

  const { data: indexesData } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => {
      const res = await indexesApi.listIndexes(1, 100);
      return res.items;
    },
  });
  const scanRoots: IndexRoot[] = indexesData || [];

  useEffect(() => {
    setPreviewState((prev) => transitionPreviewState(prev, { type: 'DIRTY_CHANGE', isDirty }));
    if (isDirty) {
      setPreviewData(null);
    }
  }, [isDirty]);

  useEffect(() => {
    setSelectedRoots(undefined);
    setPreviewData(null);
    setPreviewState(isDirty ? 'EDITING_DIRTY' : 'SAVED_PREVIEW_REQUIRED');
  }, [mode, workflowId, revision]);

  const previewMutation = useMutation({
    mutationFn: async ({ page: targetPage, pageSize: targetPageSize }: PreviewRequestParams) => {
      if (!workflowId || isDirty || isArchived) {
        throw new Error('当前状态无法执行工作流预览');
      }
      return workflowApi.previewWorkflow(workflowId, {
        revision,
        page: targetPage,
        page_size: targetPageSize,
        runtime_inputs: selectedRoots && selectedRoots.length > 0 ? { root_ids: selectedRoots } : undefined,
      });
    },
    onMutate: () => {
      setPreviewError(null);
      setErrorMessage(null);
      setPreviewState((prev) => transitionPreviewState(prev, { type: 'START_PREVIEW' }));
    },
    onSuccess: (data, variables) => {
      setPage(variables.page);
      setPageSize(variables.pageSize);
      setPreviewData(data);
      setPreviewState((prev) =>
        transitionPreviewState(prev, {
          type: 'PREVIEW_SUCCESS',
          compileDigest: data.compile_digest,
        })
      );
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      setPreviewError(structured.message || '工作流预览失败');
      setPreviewData(null);
      setPreviewState((prev) =>
        transitionPreviewState(prev, {
          type: 'PREVIEW_ERROR',
          message: structured.message,
        })
      );
    },
  });

  const handleRootsChange = (roots: number[] | undefined) => {
    const normalized = normalizeSelectedRoots(roots, mode);
    setSelectedRoots(normalized);
    setPage(1);
    setPreviewState((prev) => transitionPreviewState(prev, { type: 'ROOTS_CHANGE' }));
    setPreviewData((prev) => (prev ? { ...prev, compile_digest: '' } : null));
  };

  const generatePlanMutation = useMutation({
    mutationFn: () => {
      if (!previewData?.compile_digest) {
        throw new Error('未获取到编译摘要，无法生成计划');
      }
      return workflowApi.generatePlan(workflowId, {
        expected_compile_digest: previewData.compile_digest,
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
        // Clear digest and mark as PREVIEW_STALE, DO NOT REFETCH
        setPreviewData((prev) => (prev ? { ...prev, compile_digest: '' } : null));
        setPreviewState((prev) => transitionPreviewState(prev, { type: 'PREVIEW_CHANGED_ERROR' }));
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
      render: (_: any, __: any, idx: number) => computePreviewRowIndex(page, pageSize, idx),
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

  const getStateTag = () => {
    switch (previewState) {
      case 'EDITING_DIRTY':
        return <Tag color="warning">配置已修改，需先保存新版本</Tag>;
      case 'SAVED_PREVIEW_REQUIRED':
        return <Tag color="default">待显式生成预览</Tag>;
      case 'PREVIEWING':
        return <Tag color="processing">正在分析执行预览...</Tag>;
      case 'PREVIEW_READY':
        return <Tag color="success">预览已就绪 (可生成草稿)</Tag>;
      case 'PREVIEW_STALE':
        return <Tag color="error">预览已失效 (需重新刷新预览)</Tag>;
      default:
        return null;
    }
  };

  const canPreview = canPreviewWorkflow(isArchived) && !isDirty;
  const canDraft =
    canGenerateDraft(isArchived) &&
    !isDirty &&
    previewState === 'PREVIEW_READY' &&
    Boolean(previewData?.compile_digest) &&
    !previewMutation.isPending &&
    !generatePlanMutation.isPending;

  return (
    <Card
      title={
        <Space>
          <EyeOutlined style={{ color: '#1677ff' }} />
          <span>执行预览与批处理计划生成 (Workflow Preview & Generate Plan)</span>
          {getStateTag()}
        </Space>
      }
      bordered={false}
      style={{ borderRadius: 12, marginTop: 16 }}
      extra={
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => previewMutation.mutate({ page, pageSize })}
            loading={previewMutation.isPending}
            disabled={!canPreview}
          >
            {previewData ? '刷新预览' : '生成预览'}
          </Button>

          <Popconfirm
            title="确认基于此预览生成批处理计划草稿？"
            description="计划生成为只读草稿态，仍需冻结与校验后方可执行。"
            onConfirm={() => generatePlanMutation.mutate()}
            disabled={!canDraft}
            okText="生成草稿"
            cancelText="取消"
          >
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              disabled={!canDraft}
              loading={generatePlanMutation.isPending}
            >
              生成批处理计划草稿 (Draft)
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      {isArchived ? (
        <Alert
          type="info"
          showIcon
          message="工作流已归档"
          description="此工作流已被归档封存，处于只读模式，不可执行预览或生成批处理计划。"
          style={{ marginBottom: 16 }}
        />
      ) : isDirty ? (
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

          {previewError && (
            <Alert
              type="error"
              showIcon
              message="工作流预览失败"
              description={previewError}
              style={{ marginBottom: 16 }}
            />
          )}

          <div style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text type="secondary">覆盖根目录 (可选):</Text>
              {isOrganizer ? (
                <Select
                  placeholder="覆盖单一根目录 (整理模式仅限 1 个)"
                  value={selectedRoots?.[0]}
                  onChange={(val) => handleRootsChange(val ? [val] : undefined)}
                  style={{ minWidth: 260 }}
                  options={(scanRoots || []).map((r) => ({
                    label: `${r.root} (ID: ${r.id})`,
                    value: r.id,
                  }))}
                  allowClear
                />
              ) : (
                <Select
                  mode="multiple"
                  maxCount={16}
                  placeholder="使用步骤预设根目录 (最多16个)"
                  value={selectedRoots}
                  onChange={handleRootsChange}
                  style={{ minWidth: 260 }}
                  options={(scanRoots || []).map((r) => ({
                    label: `${r.root} (ID: ${r.id})`,
                    value: r.id,
                    disabled: !selectedRoots?.includes(r.id) && (selectedRoots?.length ?? 0) >= 16,
                  }))}
                  allowClear
                />
              )}
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

          {previewData && (
            <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
              <Descriptions size="small" column={3} bordered>
                <Descriptions.Item label="匹配文件/目录数">
                  <Text strong>{previewData.matched_count}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="计划操作总数">
                  <Text strong style={{ color: '#1677ff' }}>
                    {previewData.planned_operations_count} 项
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="预览数据源">
                  <Tag color={previewData.preview_source === 'index' ? 'blue' : 'purple'}>
                    {previewData.preview_source}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="编译摘要 (Compile Digest)" span={3}>
                  <Text code copyable style={{ fontSize: 12 }}>
                    {previewData.compile_digest || '(已失效，请重新生成预览)'}
                  </Text>
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}

          <Table
            dataSource={previewData?.items || []}
            columns={columns}
            rowKey={(r, idx) => `${r.source_path}-${r.operation}-${idx}`}
            loading={previewMutation.isPending}
            size="small"
            pagination={{
              current: page,
              pageSize,
              total: previewData?.planned_operations_count ?? 0,
              showSizeChanger: true,
              pageSizeOptions: ['20', '50', '100'],
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
                if (previewState === 'PREVIEW_READY') {
                  previewMutation.mutate({ page: p, pageSize: ps });
                }
              },
            }}
          />
        </>
      )}
    </Card>
  );
};
