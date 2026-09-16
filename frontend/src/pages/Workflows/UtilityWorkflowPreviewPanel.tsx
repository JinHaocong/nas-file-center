import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Input, message, Popconfirm, Space, Table, Tag, Typography } from 'antd';
import { EyeOutlined, ReloadOutlined, ThunderboltOutlined, WarningOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import { WorkflowUtilityCandidate, WorkflowPreviewResponse } from '../../types/workflow';
import { canGenerateDraft, canPreviewWorkflow } from '../../utils/workflowRbac';

const { Text } = Typography;

interface Props {
  workflowId: number;
  revision: number;
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const UtilityWorkflowPreviewPanel: React.FC<Props> = ({ workflowId, revision, isDirty, isArchived = false, onGeneratePlanSuccess }) => {
  const queryClient = useQueryClient();
  const [previewData, setPreviewData] = useState<WorkflowPreviewResponse | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [customPlanName, setCustomPlanName] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    setPreviewData(null);
    setSelectedCandidateIds([]);
  }, [workflowId, revision, isDirty]);

  const previewMutation = useMutation({
    mutationFn: () => workflowApi.previewWorkflow(workflowId, {
      revision,
      page: 1,
      page_size: 500,
      only_changed: false,
    }),
    onSuccess: (data) => {
      setPreviewData(data);
      setSelectedCandidateIds(
        data.utility_summary?.selected_candidate_ids ??
        data.utility_summary?.candidates.filter((candidate) => candidate.selectable && candidate.selected).map((candidate) => candidate.candidate_id) ?? []
      );
      setErrorMessage(null);
    },
    onError: (error) => setErrorMessage(formatDedupeErrorMessage(error)),
  });

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!previewData?.compile_digest) throw new Error('未获取到编译摘要，无法生成计划');
      return workflowApi.generatePlan(workflowId, {
        expected_compile_digest: previewData.compile_digest,
        revision,
        selected_candidate_ids: selectedCandidateIds,
        plan_name: customPlanName.trim() || undefined,
      });
    },
    onSuccess: (data) => {
      message.success(`批处理计划草稿 #${data.plan_id} 生成成功`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      onGeneratePlanSuccess(data.plan_id);
    },
    onError: (error) => {
      const structured = getStructuredApiError(error);
      setErrorMessage(formatDedupeErrorMessage(error));
      if (structured.code === 'PREVIEW_CHANGED') {
        setPreviewData((current) => current ? { ...current, compile_digest: '' } : null);
      }
    },
  });

  const candidates = previewData?.utility_summary?.candidates ?? [];
  const canPreview = canPreviewWorkflow(isArchived) && !isDirty;
  const canDraft = canGenerateDraft(isArchived) && !isDirty && Boolean(previewData?.compile_digest) && !previewMutation.isPending && !generateMutation.isPending;

  const columns = [
    { title: '状态', dataIndex: 'state', key: 'state', width: 150, render: (state: string, record: WorkflowUtilityCandidate) => <Tag color={state === 'READY' ? 'success' : 'warning'}>{state}{record.selectable ? '' : ' / 不可选'}</Tag> },
    { title: '包装目录 B', dataIndex: 'wrapper_path', key: 'wrapper_path', ellipsis: true },
    { title: '唯一子目录 C', dataIndex: 'child_path', key: 'child_path', ellipsis: true, render: (value?: string | null) => value || <Text type="secondary">-</Text> },
    { title: '移动目标 A/C', dataIndex: 'target_path', key: 'target_path', ellipsis: true, render: (value?: string | null) => value || <Text type="secondary">-</Text> },
  ];

  return (
    <Card
      title={<Space><EyeOutlined style={{ color: '#1677ff' }} /><span>目录工具预览与计划生成 (Utility Preview & Generate)</span></Space>}
      bordered={false}
      style={{ borderRadius: 12, marginTop: 16 }}
      extra={<Space>
        <Button icon={<ReloadOutlined />} onClick={() => previewMutation.mutate()} loading={previewMutation.isPending} disabled={!canPreview}>{previewData ? '刷新预览' : '生成预览'}</Button>
        <Popconfirm title="确认按当前勾选的 READY 候选生成草稿？" description="Generate 只会提交本次 Preview 中仍为 READY 且明确勾选的 candidate_id。" onConfirm={() => generateMutation.mutate()} disabled={!canDraft} okText="生成草稿" cancelText="取消">
          <Button type="primary" icon={<ThunderboltOutlined />} disabled={!canDraft} loading={generateMutation.isPending}>生成批处理计划草稿</Button>
        </Popconfirm>
      </Space>}
    >
      {isArchived && <Alert type="info" showIcon message="工作流已归档" description="归档状态禁止 Preview 与 Generate。" style={{ marginBottom: 16 }} />}
      {isDirty && <Alert type="warning" showIcon icon={<WarningOutlined />} message="配置已修改，需先保存新版本" description="Utility Preview 必须基于已保存的冻结定义。" style={{ marginBottom: 16 }} />}
      {errorMessage && <Alert type="error" showIcon message="操作失败" description={errorMessage} closable onClose={() => setErrorMessage(null)} style={{ marginBottom: 16 }} />}
      {!isArchived && !isDirty && <>
        <Alert type="info" showIcon message="只读发现 + 显式选择" description="READY 候选默认勾选；冲突/不安全候选不可选择。Preview 不修改文件系统，也不发送 runtime root override。" style={{ marginBottom: 16 }} />
        <Input placeholder="自定义计划名称 (可选)" value={customPlanName} onChange={(event) => setCustomPlanName(event.target.value)} style={{ width: 300, marginBottom: 16 }} />
        {previewData && <>
          <Descriptions size="small" bordered column={3} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="发现候选">{previewData.utility_summary?.candidate_count ?? 0}</Descriptions.Item>
            <Descriptions.Item label="READY">{previewData.utility_summary?.ready_count ?? 0}</Descriptions.Item>
            <Descriptions.Item label="当前选中">{selectedCandidateIds.length}</Descriptions.Item>
            <Descriptions.Item label="Scope" span={3}><Text code>{previewData.utility_summary?.scope_path || '-'}</Text></Descriptions.Item>
            <Descriptions.Item label="Compile Digest" span={3}><Text code copyable>{previewData.compile_digest || '(已失效，请重新 Preview)'}</Text></Descriptions.Item>
          </Descriptions>
          <Table<WorkflowUtilityCandidate>
            rowKey="candidate_id"
            size="small"
            dataSource={candidates}
            columns={columns}
            pagination={false}
            rowSelection={{
              selectedRowKeys: selectedCandidateIds,
              onChange: (keys) => setSelectedCandidateIds(keys.map(String)),
              getCheckboxProps: (record) => ({ disabled: !record.selectable }),
            }}
          />
        </>}
      </>}
    </Card>
  );
};
