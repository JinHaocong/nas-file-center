import React, { useEffect, useRef, useState } from 'react';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
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
import { canConfirmWorkflowModeReset, canConfirmWorkflowRollback, validateWorkflowBasicFields } from '../../utils/workflowBuilderActions';
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

const workflowModes: WorkflowMode[] = ['file', 'organizer', 'dedupe', 'utility'];

const modeIcon = (mode: WorkflowMode) => {
  if (mode === 'file') return <ConsoleIcon name="file-text" size={17} />;
  if (mode === 'organizer') return <ConsoleIcon name="folders" size={17} />;
  if (mode === 'dedupe') return <ConsoleIcon name="zap" size={17} />;
  return <ConsoleIcon name="settings" size={17} />;
};

type PendingWorkflowConfirmation =
  | { kind: 'mode'; targetMode: WorkflowMode }
  | { kind: 'back' }
  | { kind: 'rollback'; revision: number; expectedRevision: number };

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
  const formId = React.useId();
  const nameInputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [nameError, setNameError] = useState('');
  const toast = useConsoleToast();
  const rollbackInFlight = useRef(false);
  const [confirmation, setConfirmation] = useState<PendingWorkflowConfirmation | null>(null);
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
        setName(workflow.name ?? '');
      setDescription(workflow.description ?? '');
      setNameError('');
      }
      if (historicalRevisionData.definition) {
        setMode(historicalRevisionData.definition.mode || 'file');
        setSteps(historicalRevisionData.definition.steps || []);
      }
      setIsDirty(false);
    } else if (workflow && !isHistoricalView) {
      setName(workflow.name ?? '');
        setDescription(workflow.description ?? '');
        setNameError('');
      if (workflow.definition) {
        setMode(workflow.definition.mode || 'file');
        setSteps(workflow.definition.steps || []);
      }
      setIsDirty(false);
    } else if (isNew) {
      setName('');
      setDescription('');
      setNameError('');
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
  ]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const values = validateWorkflowBasicFields(name, description);
      if (values.nameError) throw new Error(values.nameError);
      const definition: WorkflowDefinition = {
        schema_version: 1,
        mode,
        steps,
      };
      if (isNew) {
        return workflowApi.createWorkflow({
          name: values.name,
          description: values.description,
          definition,
        });
      }
      if (!workflow) throw new Error('工作流数据缺失');
      return workflowApi.updateWorkflow(workflowId, {
        expected_current_revision: workflow.current_revision,
        name: values.name,
        description: values.description,
        definition,
      });
    },
    onSuccess: (res: WorkflowResponse) => {
      toast.success(isNew ? '工作流创建成功' : `工作流已保存至新版本 r${res.current_revision}`);
      setIsDirty(false);
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      if (isNew) navigate(`/workflows/${res.id}`);
      else refetch();
    },
    onError: (err) =>
      toast.error(getStructuredApiError(err).message || '保存工作流失败'),
  });

  const handleSave = () => {
    if (!canEdit || saveMutation.isPending) return;
    const values = validateWorkflowBasicFields(name, description);
    if (values.nameError) {
      setNameError(values.nameError);
      nameInputRef.current?.focus();
      return;
    }
    saveMutation.mutate();
  };

  const rollbackMutation = useMutation({
    mutationFn: (revision: number) => {
      if (!workflow) throw new Error('工作流不存在');
      return workflowApi.rollbackWorkflow(workflowId, {
        target_revision: revision,
        expected_current_revision: workflow.current_revision,
      });
    },
    onSuccess: (data) => {
      setConfirmation(null);
      toast.success(`已成功回滚至版本 r${data.current_revision}`);
      queryClient.invalidateQueries({ queryKey: ['workflowDetail', workflowId] });
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      navigate(`/workflows/${workflowId}`);
      refetch();
    },
    onError: (err) => {
      setConfirmation(null);
      toast.error(getStructuredApiError(err).message || '回滚失败');
    },
    onSettled: () => { rollbackInFlight.current = false; },
  });

  const handleModeChange = (newMode: WorkflowMode) => {
    if (!canSwitchMode || newMode === mode) return;
    if (steps.length > 0) {
      setConfirmation({ kind: 'mode', targetMode: newMode });
    } else {
      setMode(newMode);
      setSteps(defaultStepsForMode(newMode));
      setIsDirty(true);
    }
  };

  const handleStepChange = (newSteps: WorkflowStep[]) => {
    setSteps(newSteps);
    setIsDirty(true);
  };

  const handleBack = () => {
    if (isDirty) setConfirmation({ kind: 'back' });
    else navigate('/workflows');
  };

  const confirmWorkflowAction = () => {
    if (!confirmation) return;
    if (confirmation.kind === 'mode') {
      if (canConfirmWorkflowModeReset(canSwitchMode, saveMutation.isPending, mode, confirmation.targetMode)) {
        setMode(confirmation.targetMode);
        setSteps(defaultStepsForMode(confirmation.targetMode));
        setIsDirty(true);
      }
      setConfirmation(null);
      return;
    }
    if (confirmation.kind === 'back') {
      setConfirmation(null);
      navigate('/workflows');
      return;
    }
    if (rollbackInFlight.current || rollbackMutation.isPending) return;
    if (!canConfirmWorkflowRollback({
      canRollback, isHistoricalView, currentRevision: workflow?.current_revision,
      selectedRevision: targetRevision, requestedRevision: confirmation.revision,
      expectedRevision: confirmation.expectedRevision,
      busy: rollbackMutation.isPending || rollbackInFlight.current,
    })) {
      setConfirmation(null);
      return;
    }
    rollbackInFlight.current = true;
    rollbackMutation.mutate(confirmation.revision);
  };

  if (!isNew && (isLoading || (isHistoricalView && isHistLoading))) {
    return (
      <div className="nfc-centered-state nfc-v2-workflow-state" role="status">
        <span className="nfc-console-spinner" aria-hidden="true" />
        正在载入工作流配置...
      </div>
    );
  }

  if (!isNew && isError) {
    return (
      <div className="nfc-workflow-error-state nfc-v2-workflow-state is-error" role="alert">
        <h2>加载工作流失败</h2>
        <p>{getStructuredApiError(error).message}</p>
        <ConsoleButton onClick={() => navigate('/workflows')}>返回列表</ConsoleButton>
      </div>
    );
  }

  if (!isNew && !parsedRevision.isValid) {
    return (
      <div className="nfc-workflow-error-state nfc-v2-workflow-state is-error" role="alert">
        <h2>无效的历史版本号</h2>
        <p>{parsedRevision.errorMessage || '版本号参数不合法，已拒绝访问。'}</p>
        <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}
          onClick={() => navigate('/workflows/' + workflowId)}>返回当前版本</ConsoleButton>
        <ConsoleButton variant="primary" onClick={() => navigate('/workflows/' + workflowId)}>
          查看当前最新版本 (r{workflow?.current_revision ?? ''})
        </ConsoleButton>
      </div>
    );
  }

  if (!isNew && isHistoricalView && isHistError) {
    return (
      <div className="nfc-workflow-error-state nfc-v2-workflow-state is-error" role="alert">
        <h2>历史版本加载失败</h2>
        <p>{getStructuredApiError(histError).message || '指定的历史版本不存在或加载失败。'}</p>
        <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}
          onClick={() => navigate('/workflows/' + workflowId)}>返回当前版本</ConsoleButton>
        <ConsoleButton variant="primary" onClick={() => navigate('/workflows/' + workflowId)}>
          查看当前最新版本 (r{workflow?.current_revision ?? ''})
        </ConsoleButton>
      </div>
    );
  }

  if (isNew && !canCreateWorkflow(user?.role)) {
    return (
      <div className="nfc-workflow-error-state nfc-v2-workflow-state is-error" role="alert">
        <h2>权限不足</h2>
        <p>普通成员不可创建新工作流，请联系管理员。</p>
        <ConsoleButton onClick={() => navigate('/workflows')}>返回列表</ConsoleButton>
      </div>
    );
  }

  const versionLabel = isNew
    ? 'unsaved'
    : isHistoricalView
    ? `historical r${targetRevision}`
    : `r${workflow?.current_revision}`;

  return (
    <div className="nfc-operations-page nfc-workflow-builder-grid nfc-workflow-builder-page nfc-page-layout-workbench">
      <PageHeader
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
            <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}
              onClick={handleBack}>返回</ConsoleButton>
            {isHistoricalView && (
              <ConsoleButton onClick={() => navigate('/workflows/' + workflowId)}>
                返回当前最新版
              </ConsoleButton>
            )}
            {isHistoricalView && canRollback && (
              <ConsoleButton variant="danger" leadingIcon={<ConsoleIcon name="history" size={16} />}
                loading={rollbackMutation.isPending}
                onClick={() => {
                  if (workflow && targetRevision !== null && !rollbackMutation.isPending) {
                    setConfirmation({ kind: 'rollback', revision: targetRevision,
                      expectedRevision: workflow.current_revision });
                  }
                }}>
                回滚至此版本
              </ConsoleButton>
            )}
            {!isNew && workflow && (
              <ConsoleButton leadingIcon={<ConsoleIcon name="history" size={16} />}
                onClick={() => setRevisionDrawerOpen(true)}>版本历史</ConsoleButton>
            )}
            {canEdit && (
              <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="check" size={16} />}
                loading={saveMutation.isPending} disabled={!isDirty && !isNew}
                onClick={handleSave}>
                {isNew ? '创建工作流' : '保存新版本'}
              </ConsoleButton>
            )}
          </ActionBar>
        }
      />

      <div className="nfc-plan-alert-stack nfc-v2-workflow-notices">
        {isArchived && (
          <div className="nfc-v2-workflow-notice is-error" role="note">
            <ConsoleIcon name="lock" size={18} />
            <div><strong>工作流已被归档封存</strong>
              <p>归档态完全只读：禁止编辑、保存新版本、回滚、Preview 与 Generate。</p></div>
          </div>
        )}
        {isHistoricalView && (
          <div className="nfc-v2-workflow-notice" role="note">
            <ConsoleIcon name="history" size={18} />
            <div><strong>正在查看历史版本 r{targetRevision}</strong>
              <p>历史版本只读；可在允许条件下基于此版本 Preview / Generate Draft，或由管理员回滚。</p></div>
          </div>
        )}
        {!isNew && !canEdit && !isArchived && !isHistoricalView && (
          <div className="nfc-v2-workflow-notice is-warning" role="note">
            <ConsoleIcon name="shield-check" size={18} />
            <div><strong>普通成员权限提示</strong>
              <p>可查看、Preview 与 Generate Draft，但不能修改步骤、保存修订或归档。</p></div>
          </div>
        )}
      </div>

      <div className="nfc-workflow-editor-layout">
        <aside className="nfc-workflow-definition-rail">
          <DataPanel
        title="基础信息与执行模式"
        description="模式切换会重置为对应模式的标准拓扑，并需要保存为新的 revision。"
        className="nfc-complex-form-panel"
      >
        <form className="nfc-v2-workflow-form" noValidate
          onSubmit={(event) => { event.preventDefault(); handleSave(); }}>
          <div className="nfc-form-grid">
            <div className="nfc-v2-workflow-field">
              <label htmlFor={formId + '-name'}>工作流名称 <span aria-hidden="true">*</span></label>
              <input ref={nameInputRef} id={formId + '-name'} type="text" value={name}
                disabled={!canEdit} required
                placeholder="例如：下载目录自动整理归档流 / 相册清理流"
                aria-invalid={Boolean(nameError)}
                aria-describedby={nameError ? formId + '-name-error' : undefined}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameError('');
                  setIsDirty(true);
                }} />
              {nameError && <span id={formId + '-name-error'}
                className="nfc-v2-workflow-field-error" role="alert">{nameError}</span>}
            </div>
            <div className="nfc-v2-workflow-field">
              <label htmlFor={formId + '-description'}>工作流描述</label>
              <textarea id={formId + '-description'} rows={2} value={description}
                disabled={!canEdit} placeholder="描述处理逻辑、边界和目标场景..."
                onChange={(event) => {
                  setDescription(event.target.value);
                  setIsDirty(true);
                }} />
            </div>
          </div>
          <fieldset className="nfc-v2-workflow-mode-fieldset" disabled={!canSwitchMode}
            aria-describedby={formId + '-mode-help'}>
            <legend>工作流模式 <span aria-hidden="true">*</span></legend>
            <p id={formId + '-mode-help'} className="nfc-v2-workflow-field-help">
              {!canSwitchMode ? '当前状态或权限下工作流模式不可修改'
                : '切换模式将重置步骤为该模式标准拓扑'}
            </p>
            <div className="nfc-workflow-mode-grid">
              {workflowModes.map(option => (
                <label key={option}
                  className={'nfc-workflow-mode-option nfc-v2-workflow-mode-choice' +
                    (mode === option ? ' is-selected' : '')}>
                  <input type="radio" name={formId + '-mode'} value={option}
                    checked={mode === option} disabled={!canSwitchMode}
                    onChange={() => handleModeChange(option)} />
                  {modeIcon(option)}
                  <span>{modeLabel(option)}</span>
                  <small>{option}</small>
                </label>
              ))}
            </div>
          </fieldset>
        </form>
          </DataPanel>
        </aside>

        <main className="nfc-workflow-pipeline-canvas">
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
        </main>
      </div>

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

      <ConsoleConfirmDialog
        open={confirmation !== null}
        onOpenChange={open => { if (!open && !rollbackMutation.isPending) setConfirmation(null); }}
        title={confirmation?.kind === 'mode' ? '切换工作流模式'
          : confirmation?.kind === 'back' ? '未保存的更改' : '确认回滚历史版本'}
        description={confirmation?.kind === 'mode'
          ? '切换到 ' + modeLabel(confirmation.targetMode) +
            ' 将重置流水线步骤为该模式的标准默认拓扑。确定切换吗？'
          : confirmation?.kind === 'back'
            ? '当前工作流存在未保存的修改，退出将丢失这些修改，确认返回吗？'
            : '系统将基于历史版本 r' +
              (confirmation?.kind === 'rollback' ? confirmation.revision : '') +
              ' 的定义生成新修订版本并恢复至当前。'}
        confirmText={confirmation?.kind === 'mode' ? '确认重置并切换'
          : confirmation?.kind === 'back' ? '确认退出' : '确认回滚'}
        danger={confirmation?.kind !== 'mode'}
        busy={rollbackMutation.isPending && confirmation?.kind === 'rollback'}
        disabled={confirmation?.kind === 'mode' && !canSwitchMode}
        onConfirm={confirmWorkflowAction}
      />

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
