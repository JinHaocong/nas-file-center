import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Spin,
  message,
} from 'antd';
import {
  AppstoreOutlined,
  ArrowLeftOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  HistoryOutlined,
  SaveOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import {
  WorkflowDefinition,
  WorkflowMode,
  WorkflowResponse,
  WorkflowStep,
} from '../../types/workflow';
import { StepList } from '../../components/workflows/StepList';
import { RevisionDrawer } from '../../components/workflows/RevisionDrawer';
import { WorkflowPreviewPanel } from './WorkflowPreviewPanel';
import { useTitle } from '../../hooks/useTitle';
import { useAuth } from '../../contexts/AuthContext';
import {
  canCreateWorkflow,
  canRollbackWorkflow,
  canSaveRevision,
  canSwitchWorkflowMode,
} from '../../utils/workflowRbac';
import { createDefaultOrganizerSnapshot } from '../../utils/organizerDefaults';
import { createDefaultDedupeScorerConfig } from '../../utils/dedupeConfig';
import { createInitialScanStep, parseWorkflowRevisionQuery } from '../../utils/workflowRevisionParser';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';

const defaultStepsForMode = (mode: WorkflowMode): WorkflowStep[] => {
  if (mode === 'file') return [createInitialScanStep('step_scan_1')];
  if (mode === 'organizer') {
    return [
      createInitialScanStep('step_scan_1'),
      {
        id: 'step_organize_1',
        type: 'organize',
        profile_snapshot: createDefaultOrganizerSnapshot('默认整理快照'),
      },
    ];
  }
  if (mode === 'dedupe') {
    return [
      {
        id: 'step_dedupe_1',
        type: 'dedupe',
        scorer_config: createDefaultDedupeScorerConfig(),
      },
    ];
  }
  return [
    {
      id: 'step_utility_collapse_1',
      type: 'single_child_wrapper_collapse',
      root_id: 0,
      subpath: '',
    },
  ];
};

const modeLabel = (mode: WorkflowMode) => {
  if (mode === 'file') return '文件规则流';
  if (mode === 'organizer') return '目录整理流';
  if (mode === 'dedupe') return '高级去重流';
  return '目录工具流';
};

const modeIcon = (mode: WorkflowMode) => {
  if (mode === 'file') return <FileTextOutlined />;
  if (mode === 'organizer') return <AppstoreOutlined />;
  if (mode === 'dedupe') return <ThunderboltOutlined />;
  return <ToolOutlined />;
};

export const WorkflowBuilderPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const workflowId = isNew ? 0 : Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const revisionQuery = searchParams.get('revision');
  useTitle(isNew ? '新建工作流' : `编辑工作流 #${workflowId}`);
  const { user } = useAuth();
  const [form] = Form.useForm();
  const [mode, setMode] = useState<WorkflowMode>('file');
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [isDirty, setIsDirty] = useState(false);
  const [revisionDrawerOpen, setRevisionDrawerOpen] = useState(false);

  const { data: workflow, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['workflowDetail', workflowId],
    queryFn: () => workflowApi.getWorkflow(workflowId),
    enabled: !isNew && Boolean(workflowId),
  });

  const parsedRevision = parseWorkflowRevisionQuery(revisionQuery, workflow?.current_revision);
  const isHistoricalView = parsedRevision.isValid && parsedRevision.isHistorical;
  const targetRevision = parsedRevision.revision;

  const {
    data: historicalRevisionData,
    isLoading: isHistLoading,
    isError: isHistError,
    error: histError,
  } = useQuery({
    queryKey: ['workflowRevisionDetail', workflowId, targetRevision],
    queryFn: () => workflowApi.getRevision(workflowId, targetRevision!),
    enabled: !isNew && Boolean(workflowId) && isHistoricalView && targetRevision !== null,
  });

  const isArchived = Boolean(workflow?.archived_at);
  const isBuiltin = Boolean(workflow?.is_builtin);
  const canEdit =
    !isHistoricalView &&
    !isArchived &&
    !isBuiltin &&
    (isNew ? canCreateWorkflow(user?.role) : canSaveRevision(user?.role, isArchived));
  const canRollback =
    isHistoricalView &&
    canRollbackWorkflow(user?.role, isArchived) &&
    !isBuiltin;
  const canSwitchMode = isNew
    ? canEdit
    : canSwitchWorkflowMode(user?.role, {
        isBuiltin,
        isArchived,
        isHistorical: isHistoricalView,
      });

  useEffect(() => {
    if (!parsedRevision.isValid) return;
    if (isHistoricalView && historicalRevisionData) {
      if (workflow) {
        form.setFieldsValue({
          name: workflow.name,
          description: workflow.description,
        });
      }
      if (historicalRevisionData.definition) {
        setMode(historicalRevisionData.definition.mode || 'file');
        setSteps(historicalRevisionData.definition.steps || []);
      }
      setIsDirty(false);
    } else if (workflow && !isHistoricalView) {
      form.setFieldsValue({
        name: workflow.name,
        description: workflow.description,
      });
      if (workflow.definition) {
        setMode(workflow.definition.mode || 'file');
        setSteps(workflow.definition.steps || []);
      }
      setIsDirty(false);
    } else if (isNew) {
      form.resetFields();
      form.setFieldsValue({ name: '', description: '' });
      setMode('file');
      setSteps(defaultStepsForMode('file'));
      setIsDirty(false);
    }
  }, [
    workflow,
    parsedRevision.isValid,
    isHistoricalView,
    targetRevision,
    historicalRevisionData,
    isNew,
    form,
  ]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      const definition: WorkflowDefinition = {
        schema_version: 1,
        mode,
        steps,
      };
      if (isNew) {
        return workflowApi.createWorkflow({
          name: values.name.trim(),
          description: values.description?.trim() || '',
          definition,
        });
      }
      if (!workflow) throw new Error('工作流数据缺失');
      return workflowApi.updateWorkflow(workflowId, {
        expected_current_revision: workflow.current_revision,
        name: values.name.trim(),
        description: values.description?.trim() || '',
        definition,
      });
    },
    onSuccess: (res: WorkflowResponse) => {
      message.success(
        isNew ? '工作流创建成功' : `工作流已保存至新版本 r${res.current_revision}`
      );
      setIsDirty(false);
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      if (isNew) navigate(`/workflows/${res.id}`);
      else refetch();
    },
    onError: (err) =>
      message.error(getStructuredApiError(err).message || '保存工作流失败'),
  });

  const rollbackMutation = useMutation({
    mutationFn: (revision: number) => {
      if (!workflow) throw new Error('工作流不存在');
      return workflowApi.rollbackWorkflow(workflowId, {
        target_revision: revision,
        expected_current_revision: workflow.current_revision,
      });
    },
    onSuccess: (data) => {
      message.success(`已成功回滚至版本 r${data.current_revision}`);
      queryClient.invalidateQueries({ queryKey: ['workflowDetail', workflowId] });
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      navigate(`/workflows/${workflowId}`);
      refetch();
    },
    onError: (err) =>
      message.error(getStructuredApiError(err).message || '回滚失败'),
  });

  const handleModeChange = (newMode: WorkflowMode) => {
    if (newMode === mode) return;
    const apply = () => {
      setMode(newMode);
      setSteps(defaultStepsForMode(newMode));
      setIsDirty(true);
    };
    if (steps.length > 0) {
      Modal.confirm({
        title: '切换工作流模式',
        icon: <ExclamationCircleOutlined />,
        content: `切换到 ${modeLabel(newMode)} 将重置流水线步骤为该模式的标准默认拓扑。确定切换吗？`,
        okText: '确认重置并切换',
        cancelText: '取消',
        onOk: apply,
      });
    } else {
      apply();
    }
  };

  const handleStepChange = (newSteps: WorkflowStep[]) => {
    setSteps(newSteps);
    setIsDirty(true);
  };

  const handleBack = () => {
    if (isDirty) {
      Modal.confirm({
        title: '未保存的更改',
        icon: <ExclamationCircleOutlined />,
        content: '当前工作流存在未保存的修改，退出将丢失这些修改，确认返回吗？',
        okText: '确认退出',
        cancelText: '留在此页',
        onOk: () => navigate('/workflows'),
      });
    } else {
      navigate('/workflows');
    }
  };

  if (!isNew && (isLoading || (isHistoricalView && isHistLoading))) {
    return (
      <div className="nfc-centered-state">
        <Spin size="large" tip="正在载入工作流配置..." />
      </div>
    );
  }

  if (!isNew && isError) {
    return (
      <Alert
        type="error"
        showIcon
        message="加载工作流失败"
        description={getStructuredApiError(error).message}
        action={<Button onClick={() => navigate('/workflows')}>返回列表</Button>}
      />
    );
  }

  if (!isNew && !parsedRevision.isValid) {
    return (
      <div className="nfc-workflow-error-state">
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(`/workflows/${workflowId}`)}
        >
          返回当前版本
        </Button>
        <Alert
          type="error"
          showIcon
          message="无效的历史版本号"
          description={parsedRevision.errorMessage || '版本号参数不合法，已拒绝访问。'}
          action={
            <Button
              type="primary"
              onClick={() => navigate(`/workflows/${workflowId}`)}
            >
              查看当前最新版本 (r{workflow?.current_revision ?? ''})
            </Button>
          }
        />
      </div>
    );
  }

  if (!isNew && isHistoricalView && isHistError) {
    return (
      <div className="nfc-workflow-error-state">
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(`/workflows/${workflowId}`)}
        >
          返回当前版本
        </Button>
        <Alert
          type="error"
          showIcon
          message="历史版本加载失败"
          description={
            getStructuredApiError(histError).message ||
            '指定的历史版本不存在或加载失败。'
          }
          action={
            <Button
              type="primary"
              onClick={() => navigate(`/workflows/${workflowId}`)}
            >
              查看当前最新版本 (r{workflow?.current_revision ?? ''})
            </Button>
          }
        />
      </div>
    );
  }

  if (isNew && !canCreateWorkflow(user?.role)) {
    return (
      <Alert
        type="error"
        showIcon
        message="权限不足"
        description="普通成员不可创建新工作流，请联系管理员。"
        action={<Button onClick={() => navigate('/workflows')}>返回列表</Button>}
      />
    );
  }

  const versionLabel = isNew
    ? 'unsaved'
    : isHistoricalView
    ? `historical r${targetRevision}`
    : `r${workflow?.current_revision}`;

  return (
    <div className="nfc-operations-page nfc-workflow-builder-grid">
      <PageHeader
        eyebrow="WORKFLOW BUILDER"
        title={isNew ? '新建工作流' : workflow?.name || `工作流 #${workflowId}`}
        description={
          <div className="nfc-plan-header-meta">
            <span className="nfc-kind-badge">{versionLabel}</span>
            <span className="nfc-kind-badge">{modeLabel(mode)}</span>
            {isArchived && <span className="nfc-status-badge nfc-status-danger"><span className="nfc-status-dot" />已归档</span>}
            {isBuiltin && <span className="nfc-kind-badge">builtin / readonly</span>}
            {isDirty && <span className="nfc-status-badge nfc-status-warning"><span className="nfc-status-dot" />未保存修改</span>}
          </div>
        }
        actions={
          <ActionBar compact>
            <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>返回</Button>
            {isHistoricalView && (
              <Button onClick={() => navigate(`/workflows/${workflowId}`)}>
                返回当前最新版
              </Button>
            )}
            {isHistoricalView && canRollback && (
              <Popconfirm
                title={`确认回滚至历史版本 r${targetRevision}？`}
                description="系统将基于此定义生成新修订版本并恢复至当前。"
                onConfirm={() => rollbackMutation.mutate(targetRevision!)}
                okText="确认回滚"
                cancelText="取消"
              >
                <Button danger icon={<HistoryOutlined />} loading={rollbackMutation.isPending}>
                  回滚至此版本
                </Button>
              </Popconfirm>
            )}
            {!isNew && workflow && (
              <Button
                icon={<HistoryOutlined />}
                onClick={() => setRevisionDrawerOpen(true)}
              >
                版本历史
              </Button>
            )}
            {canEdit && (
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saveMutation.isPending}
                disabled={!isDirty && !isNew}
                onClick={() => saveMutation.mutate()}
              >
                {isNew ? '创建工作流' : '保存新版本'}
              </Button>
            )}
          </ActionBar>
        }
      />

      <div className="nfc-plan-alert-stack">
        {isArchived && (
          <Alert
            type="error"
            showIcon
            message="工作流已被归档封存"
            description="归档态完全只读：禁止编辑、保存新版本、回滚、Preview 与 Generate。"
          />
        )}
        {isHistoricalView && (
          <Alert
            type="info"
            showIcon
            message={`正在查看历史版本 r${targetRevision}`}
            description="历史版本只读；可在允许条件下基于此版本 Preview / Generate Draft，或由管理员回滚。"
          />
        )}
        {!isNew && !canEdit && !isArchived && !isHistoricalView && (
          <Alert
            type="warning"
            showIcon
            message="普通成员权限提示"
            description="可查看、Preview 与 Generate Draft，但不能修改步骤、保存修订或归档。"
          />
        )}
      </div>

      <DataPanel
        title="基础信息与执行模式"
        description="模式切换会重置为对应模式的标准拓扑，并需要保存为新的 revision。"
        className="nfc-complex-form-panel"
      >
        <Form
          form={form}
          layout="vertical"
          onValuesChange={() => setIsDirty(true)}
          disabled={!canEdit}
        >
          <div className="nfc-form-grid">
            <Form.Item
              name="name"
              label="工作流名称"
              rules={[{ required: true, message: '请输入工作流名称' }]}
            >
              <Input placeholder="例如：下载目录自动整理归档流 / 相册清理流" />
            </Form.Item>
            <Form.Item name="description" label="工作流描述">
              <Input.TextArea
                rows={2}
                placeholder="描述处理逻辑、边界和目标场景..."
              />
            </Form.Item>
          </div>

          <Form.Item
            label="工作流模式"
            required
            extra={
              !canSwitchMode
                ? '当前状态或权限下工作流模式不可修改'
                : '切换模式将重置步骤为该模式标准拓扑'
            }
          >
            <Radio.Group
              value={mode}
              onChange={(event) => handleModeChange(event.target.value)}
              disabled={!canSwitchMode}
              className="nfc-workflow-mode-grid"
            >
              {(['file', 'organizer', 'dedupe', 'utility'] as WorkflowMode[]).map(
                (candidate) => (
                  <Radio.Button value={candidate} key={candidate}>
                    <span className="nfc-workflow-mode-option">
                      {modeIcon(candidate)}
                      <span>{modeLabel(candidate)}</span>
                      <small>{candidate}</small>
                    </span>
                  </Radio.Button>
                )
              )}
            </Radio.Group>
          </Form.Item>
        </Form>
      </DataPanel>

      <DataPanel
        title="流水线执行步骤"
        description="步骤严格自上而下线性执行；Preview 使用已保存 revision 作为权威定义。"
      >
        <StepList
          steps={steps}
          mode={mode}
          readOnly={!canEdit}
          onChange={handleStepChange}
        />
      </DataPanel>

      {!isNew &&
        workflow &&
        (!isHistoricalView || Boolean(historicalRevisionData)) && (
          <WorkflowPreviewPanel
            workflowId={workflow.id}
            revision={isHistoricalView ? targetRevision! : workflow.current_revision}
            mode={mode}
            isDirty={isDirty}
            isArchived={isArchived}
            onGeneratePlanSuccess={(planId) => navigate(`/plans/${planId}`)}
          />
        )}

      {!isNew && workflow && (
        <RevisionDrawer
          open={revisionDrawerOpen}
          workflowId={workflow.id}
          currentRevision={workflow.current_revision}
          isBuiltin={workflow.is_builtin}
          isArchived={isArchived}
          onClose={() => setRevisionDrawerOpen(false)}
          onRollbackSuccess={() => refetch()}
        />
      )}
    </div>
  );
};
