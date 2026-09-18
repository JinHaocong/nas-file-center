import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  Popconfirm,
  Table,
  message,
} from 'antd';
import {
  EyeOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import {
  WorkflowPreviewResponse,
  WorkflowUtilityCandidate,
} from '../../types/workflow';
import { canGenerateDraft, canPreviewWorkflow } from '../../utils/workflowRbac';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';

interface Props {
  workflowId: number;
  revision: number;
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const UtilityWorkflowPreviewPanel: React.FC<Props> = ({
  workflowId,
  revision,
  isDirty,
  isArchived = false,
  onGeneratePlanSuccess,
}) => {
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
    mutationFn: () =>
      workflowApi.previewWorkflow(workflowId, {
        revision,
        page: 1,
        page_size: 500,
        only_changed: false,
      }),
    onSuccess: (data) => {
      setPreviewData(data);
      setSelectedCandidateIds(
        data.utility_summary?.selected_candidate_ids ??
          data.utility_summary?.candidates
            .filter((candidate) => candidate.selectable && candidate.selected)
            .map((candidate) => candidate.candidate_id) ??
          []
      );
      setErrorMessage(null);
    },
    onError: (error) => setErrorMessage(formatDedupeErrorMessage(error)),
  });

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!previewData?.compile_digest) {
        throw new Error('未获取到编译摘要，无法生成计划');
      }
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
        setPreviewData((current) =>
          current ? { ...current, compile_digest: '' } : null
        );
      }
    },
  });

  const candidates = previewData?.utility_summary?.candidates ?? [];
  const unsupportedCandidates = candidates.filter(
    (candidate) =>
      candidate.state === 'UNSUPPORTED_FILESYSTEM' ||
      candidate.capability_reason === 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM'
  );
  const canPreview = canPreviewWorkflow(isArchived) && !isDirty;
  const canDraft =
    canGenerateDraft(isArchived) &&
    !isDirty &&
    Boolean(previewData?.compile_digest) &&
    selectedCandidateIds.length > 0 &&
    !previewMutation.isPending &&
    !generateMutation.isPending;

  const toggleCandidate = (candidate: WorkflowUtilityCandidate, checked: boolean) => {
    if (!candidate.selectable) return;
    setSelectedCandidateIds((current) =>
      checked
        ? Array.from(new Set([...current, candidate.candidate_id]))
        : current.filter((id) => id !== candidate.candidate_id)
    );
  };

  const columns = [
    {
      title: '状态',
      dataIndex: 'state',
      key: 'state',
      width: 180,
      render: (state: string, record: WorkflowUtilityCandidate) => (
        <StatusBadge
          status={state === 'READY' ? 'ready' : 'paused'}
          label={`${state}${record.selectable ? '' : ' / 不可选'}`}
        />
      ),
    },
    {
      title: '包装目录 B',
      dataIndex: 'wrapper_path',
      key: 'wrapper_path',
      render: (value: string) => <CodePath value={value} />,
    },
    {
      title: '唯一子目录 C',
      dataIndex: 'child_path',
      key: 'child_path',
      render: (value?: string | null) => <CodePath value={value} muted={!value} />,
    },
    {
      title: '移动目标 A/C',
      dataIndex: 'target_path',
      key: 'target_path',
      render: (value?: string | null) => <CodePath value={value} muted={!value} />,
    },
  ];

  const descriptions = previewData
    ? [
        {
          label: '发现候选',
          value: previewData.utility_summary?.candidate_count ?? 0,
          emphasis: true,
        },
        {
          label: 'READY',
          value: previewData.utility_summary?.ready_count ?? 0,
          emphasis: true,
        },
        {
          label: '当前选中',
          value: selectedCandidateIds.length,
          emphasis: true,
        },
        {
          label: 'Scope',
          value: <CodePath value={previewData.utility_summary?.scope_path} />,
        },
        {
          label: 'Compile Digest',
          value: (
            <span className="nfc-mono nfc-digest-value">
              {previewData.compile_digest || '(已失效，请重新 Preview)'}
            </span>
          ),
        },
      ]
    : [];

  return (
    <DataPanel
      title="目录工具预览与计划生成"
      description="只读发现 READY 候选，并按明确选择的 candidate_id 生成 Draft。"
      action={
        <ActionBar compact>
          <Button
            icon={previewData ? <ReloadOutlined /> : <EyeOutlined />}
            onClick={() => previewMutation.mutate()}
            loading={previewMutation.isPending}
            disabled={!canPreview}
          >
            {previewData ? '刷新预览' : '生成预览'}
          </Button>
          <Popconfirm
            title="确认按当前勾选的 READY 候选生成草稿？"
            description="Generate 只提交本次 Preview 中仍为 READY 且明确勾选的 candidate_id。"
            onConfirm={() => generateMutation.mutate()}
            disabled={!canDraft}
            okText="生成草稿"
            cancelText="取消"
          >
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              disabled={!canDraft}
              loading={generateMutation.isPending}
            >
              生成计划草稿
            </Button>
          </Popconfirm>
        </ActionBar>
      }
      className="nfc-workflow-preview-panel"
    >
      <div className="nfc-workflow-preview-body">
        {isArchived && (
          <Alert
            type="info"
            showIcon
            message="工作流已归档"
            description="归档状态禁止 Preview 与 Generate。"
          />
        )}
        {isDirty && (
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            message="配置已修改，需先保存新版本"
            description="Utility Preview 必须基于已保存的冻结定义。"
          />
        )}
        {errorMessage && (
          <Alert
            type="error"
            showIcon
            message="操作失败"
            description={errorMessage}
            closable
            onClose={() => setErrorMessage(null)}
          />
        )}

        {!isArchived && !isDirty && (
          <>
            <Alert
              type="info"
              showIcon
              message="只读发现 + 显式选择"
              description="READY 默认勾选；冲突/不安全候选不可选择。Preview 不修改文件系统，也不发送 runtime root override。"
            />
            {unsupportedCandidates.length > 0 && (
              <Alert
                type="warning"
                showIcon
                icon={<WarningOutlined />}
                message="当前文件系统不支持 Utility MOVE"
                description="拓扑发现保持只读；当前文件系统不支持严格 no-overwrite MOVE。Gate6-B 不会尝试兼容 rename fallback，因此这些候选保持不可选择，也不会生成 Draft。"
              />
            )}

            <Input
              placeholder="自定义计划名称 (可选)"
              value={customPlanName}
              onChange={(event) => setCustomPlanName(event.target.value)}
              className="nfc-workflow-plan-name-input"
            />

            {previewData && (
              <>
                <ResponsiveDescriptions items={descriptions} />
                <ResponsiveDataView
                  desktop={
                    <Table<WorkflowUtilityCandidate>
                      rowKey="candidate_id"
                      size="small"
                      dataSource={candidates}
                      columns={columns}
                      pagination={false}
                      rowSelection={{
                        selectedRowKeys: selectedCandidateIds,
                        onChange: (keys) =>
                          setSelectedCandidateIds(keys.map(String)),
                        getCheckboxProps: (record) => ({
                          disabled: !record.selectable,
                        }),
                      }}
                    />
                  }
                  mobile={
                    <div className="nfc-mobile-record-list">
                      {candidates.length === 0 ? (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="暂无 Utility 候选"
                        />
                      ) : (
                        candidates.map((candidate) => (
                          <article
                            className="nfc-utility-candidate-mobile-card"
                            key={candidate.candidate_id}
                          >
                            <div className="nfc-mobile-record-heading">
                              <div className="nfc-quarantine-mobile-id">
                                <Checkbox
                                  checked={selectedCandidateIds.includes(candidate.candidate_id)}
                                  disabled={!candidate.selectable}
                                  onChange={(event) =>
                                    toggleCandidate(candidate, event.target.checked)
                                  }
                                />
                                <span className="nfc-mono">
                                  {candidate.candidate_id}
                                </span>
                              </div>
                              <StatusBadge
                                status={candidate.state === 'READY' ? 'ready' : 'paused'}
                                label={candidate.state}
                              />
                            </div>
                            <div className="nfc-plan-item-paths">
                              <div className="nfc-plan-item-path-row">
                                <span>Wrapper B</span>
                                <CodePath value={candidate.wrapper_path} />
                              </div>
                              <div className="nfc-plan-item-path-row">
                                <span>Child C</span>
                                <CodePath value={candidate.child_path} muted />
                              </div>
                              <div className="nfc-plan-item-path-row">
                                <span>Target</span>
                                <CodePath value={candidate.target_path} muted />
                              </div>
                            </div>
                            {!candidate.selectable && (
                              <p className="nfc-mobile-record-note">
                                此候选不可选择，不会进入 Draft。
                              </p>
                            )}
                          </article>
                        ))
                      )}
                    </div>
                  }
                />
              </>
            )}
          </>
        )}
      </div>
    </DataPanel>
  );
};
