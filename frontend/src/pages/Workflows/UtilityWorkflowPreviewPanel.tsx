import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import type {
  WorkflowPreviewResponse, WorkflowUtilityCandidate, WorkflowGeneratePlanRequest,
} from '../../types/workflow';
import { canGenerateDraft, canPreviewWorkflow } from '../../utils/workflowRbac';
import {
  initialUtilityCandidateIds, sameUtilityDraftRequest, sanitizeUtilityCandidateIds,
  selectableUtilityCandidateIds, utilityDraftRequest,
} from '../../utils/workflowUtilityDraft';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

interface Props {
  workflowId: number;
  revision: number;
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

type PreviewRequest = { key: string; requestId: number; workflowId: number; revision: number };
type GenerateRequest = { workflowId: number; snapshot: WorkflowGeneratePlanRequest };

export const UtilityWorkflowPreviewPanel: React.FC<Props> = ({
  workflowId, revision, isDirty, isArchived = false, onGeneratePlanSuccess,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const contextKey = [workflowId, revision, Number(isDirty), Number(isArchived)].join(':');
  const currentContext = useRef(contextKey);
  currentContext.current = contextKey;
  const previewSequence = useRef(0);
  const previewInFlight = useRef(false);
  const draftInFlight = useRef(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [previewContext, setPreviewContext] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<WorkflowPreviewResponse | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [customPlanName, setCustomPlanName] = useState('');
  const [confirmation, setConfirmation] = useState<WorkflowGeneratePlanRequest | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    previewSequence.current += 1;
    previewInFlight.current = false;
    setPreviewData(null);
    setPreviewContext(null);
    setSelectedCandidateIds([]);
    setConfirmation(null);
    setErrorMessage(null);
  }, [workflowId, revision, isDirty, isArchived]);

  const previewMutation = useMutation({
    mutationFn: ({ workflowId: targetId, revision: targetRevision }: PreviewRequest) =>
      workflowApi.previewWorkflow(targetId, {
        revision: targetRevision,
        page: 1,
        page_size: 500,
        only_changed: false,
      }),
    onSuccess: (data, request) => {
      if (request.key !== currentContext.current || request.requestId !== previewSequence.current) return;
      if (data.workflow_id !== request.workflowId ||
          (data.workflow_revision ?? data.revision) !== request.revision) {
        setErrorMessage('服务端预览版本与当前工作流不一致，请重新 Preview。');
        return;
      }
      setPreviewData(data);
      setPreviewContext(request.key);
      setSelectedCandidateIds(initialUtilityCandidateIds(data.utility_summary));
      setErrorMessage(null);
    },
    onError: (error, request) => {
      if (request.key === currentContext.current && request.requestId === previewSequence.current) {
        setErrorMessage(formatDedupeErrorMessage(error));
      }
    },
    onSettled: (_data, _error, request) => {
      if (request.requestId === previewSequence.current) previewInFlight.current = false;
    },
  });

  const generateMutation = useMutation({
    mutationFn: ({ workflowId: targetId, snapshot }: GenerateRequest) =>
      workflowApi.generatePlan(targetId, snapshot),
  });

  const canPreview = canPreviewWorkflow(isArchived) && !isDirty;
  const activePreview = previewContext === contextKey ? previewData : null;
  const candidates = activePreview?.utility_summary?.candidates ?? [];
  const selectableIds = selectableUtilityCandidateIds(candidates);
  const unsupportedCandidates = candidates.filter(candidate =>
    candidate.state === 'UNSUPPORTED_FILESYSTEM' ||
    candidate.capability_reason === 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM'
  );
  const requestNow = utilityDraftRequest({
    preview: activePreview,
    workflowId, revision, contextValid: previewContext === contextKey,
    isDirty, isArchived,
    previewPending: previewMutation.isPending || previewInFlight.current,
    generatePending: generateMutation.isPending || draftBusy,
    selectedCandidateIds,
  }, customPlanName);
  const canDraft = canGenerateDraft(isArchived) && requestNow !== null;
  const allSelected = selectableIds.length > 0 &&
    selectableIds.every(id => selectedCandidateIds.includes(id));

  const handlePreview = () => {
    if (!canPreview || previewInFlight.current || draftInFlight.current || generateMutation.isPending) return;
    previewInFlight.current = true;
    const requestId = ++previewSequence.current;
    setPreviewContext(null);
    setPreviewData(null);
    setSelectedCandidateIds([]);
    setConfirmation(null);
    setErrorMessage(null);
    previewMutation.mutate({ key: contextKey, requestId, workflowId, revision });
  };

  const toggleCandidate = (candidate: WorkflowUtilityCandidate, checked: boolean) => {
    if (!activePreview || !canPreview || previewMutation.isPending ||
        draftInFlight.current || !candidate.selectable || candidate.state !== 'READY') return;
    setSelectedCandidateIds(current => sanitizeUtilityCandidateIds(
      candidates,
      checked ? [...current, candidate.candidate_id] : current.filter(id => id !== candidate.candidate_id),
    ));
    setConfirmation(null);
  };

  const toggleAll = (checked: boolean) => {
    if (!activePreview || !canPreview || previewMutation.isPending || draftInFlight.current) return;
    setSelectedCandidateIds(checked ? [...selectableIds] : []);
    setConfirmation(null);
  };

  const handleGenerate = async () => {
    if (draftInFlight.current || !confirmation || !canDraft ||
        !sameUtilityDraftRequest(confirmation, requestNow)) {
      setConfirmation(null);
      return;
    }
    const requestKey = contextKey;
    const snapshot: WorkflowGeneratePlanRequest = {
      ...confirmation,
      selected_candidate_ids: [...(confirmation.selected_candidate_ids || [])],
    };
    draftInFlight.current = true;
    setDraftBusy(true);
    setErrorMessage(null);
    try {
      const data = await generateMutation.mutateAsync({ workflowId, snapshot });
      if (requestKey !== currentContext.current) return;
      toast.success('批处理计划草稿 #' + data.plan_id + ' 生成成功');
      void queryClient.invalidateQueries({ queryKey: ['plansList'] });
      onGeneratePlanSuccess(data.plan_id);
    } catch (error) {
      if (requestKey !== currentContext.current) return;
      const structured = getStructuredApiError(error);
      setErrorMessage(formatDedupeErrorMessage(error));
      if (structured.code === 'PREVIEW_CHANGED') {
        setPreviewData(current => current ? { ...current, compile_digest: '' } : null);
        setSelectedCandidateIds([]);
      }
    } finally {
      draftInFlight.current = false;
      setDraftBusy(false);
      setConfirmation(null);
    }
  };

  const descriptions = activePreview ? [
    { label: '发现候选', value: activePreview.utility_summary?.candidate_count ?? 0, emphasis: true },
    { label: 'READY', value: activePreview.utility_summary?.ready_count ?? 0, emphasis: true },
    { label: '当前选中', value: selectedCandidateIds.length, emphasis: true },
    { label: 'Scope', value: <CodePath value={activePreview.utility_summary?.scope_path} /> },
    { label: 'Compile Digest',
      value: <span className="nfc-mono nfc-digest-value">
        {activePreview.compile_digest || '(已失效，请重新 Preview)'}
      </span> },
  ] : [];

  const selectCandidate = (candidate: WorkflowUtilityCandidate) => (
    <input type="checkbox" aria-label={'选择候选 ' + candidate.candidate_id}
      checked={selectedCandidateIds.includes(candidate.candidate_id)}
      disabled={!canPreview || draftBusy || !candidate.selectable || candidate.state !== 'READY'}
      onChange={event => toggleCandidate(candidate, event.target.checked)} />
  );
  const candidateStatus = (candidate: WorkflowUtilityCandidate) => (
    <StatusBadge status={candidate.state === 'READY' ? 'ready' : 'paused'}
      label={candidate.state + (candidate.selectable ? '' : ' / 不可选')} />
  );

  return (
    <DataPanel
      title="目录工具预览与计划生成"
      description="只读发现 READY 候选，并按明确选择的 candidate_id 生成 Draft。"
      action={<ActionBar compact>
        <ConsoleButton leadingIcon={<ConsoleIcon name={activePreview ? 'refresh' : 'file-search'} size={16} />}
          onClick={handlePreview} loading={previewMutation.isPending}
          disabled={!canPreview || previewInFlight.current || draftBusy || generateMutation.isPending}>
          {activePreview ? '刷新预览' : '生成预览'}
        </ConsoleButton>
        <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="zap" size={16} />}
          onClick={() => { if (canDraft) setConfirmation(requestNow); }}
          disabled={!canDraft} loading={draftBusy || generateMutation.isPending}>
          生成计划草稿
        </ConsoleButton>
      </ActionBar>}
      className="nfc-workflow-preview-panel nfc-v2-utility-preview"
    >
      <div className="nfc-workflow-preview-body nfc-v2-utility-body">
        {isArchived && (
          <div className="nfc-v2-utility-notice" role="note">
            <ConsoleIcon name="info" size={18} />
            <div><strong>工作流已归档</strong><p>归档状态禁止 Preview 与 Generate。</p></div>
          </div>
        )}
        {isDirty && (
          <div className="nfc-v2-utility-notice is-warning" role="alert">
            <ConsoleIcon name="info" size={18} />
            <div><strong>配置已修改，需先保存新版本</strong>
              <p>Utility Preview 必须基于已保存的冻结定义。</p></div>
          </div>
        )}
        {errorMessage && (
          <div className="nfc-v2-utility-notice is-error" role="alert">
            <ConsoleIcon name="info" size={18} />
            <div><strong>操作失败</strong><p>{errorMessage}</p></div>
            <button type="button" aria-label="关闭错误提示" onClick={() => setErrorMessage(null)}>
              <ConsoleIcon name="x" size={16} />
            </button>
          </div>
        )}
        {!isArchived && !isDirty && (
          <>
            <div className="nfc-v2-utility-notice" role="note">
              <ConsoleIcon name="shield-check" size={18} />
              <div><strong>只读发现 + 显式选择</strong>
                <p>READY 默认勾选；冲突/不安全候选不可选择。Preview 不修改文件系统，也不发送 runtime root override。</p></div>
            </div>
            {unsupportedCandidates.length > 0 && (
              <div className="nfc-v2-utility-notice is-warning" role="alert">
                <ConsoleIcon name="info" size={18} />
                <div><strong>当前存储未通过安全无覆盖 MOVE 能力验证</strong>
                  <p>当前存储既不支持原生 RENAME_NOREPLACE，也未通过目录 rename 的严格 no-clobber 探测。为避免并发目标被覆盖，这些候选不可选择，也不会生成 Draft。</p></div>
              </div>
            )}
            <label className="nfc-v2-utility-plan-name">
              自定义计划名称（可选）
              <input type="text" value={customPlanName} placeholder="自定义计划名称 (可选)"
                className="nfc-workflow-plan-name-input"
                disabled={draftBusy || generateMutation.isPending}
                onChange={event => { setCustomPlanName(event.target.value); setConfirmation(null); }} />
            </label>
            {previewMutation.isPending && (
              <p className="nfc-v2-utility-feedback" role="status">正在生成只读 Preview…</p>
            )}
            {activePreview && (
              <>
                <ResponsiveDescriptions items={descriptions} />
                <div className="nfc-v2-utility-selection-bar">
                  <label>
                    <input type="checkbox" aria-label="选择全部 READY 候选"
                      checked={allSelected} disabled={selectableIds.length === 0 || draftBusy ||
                        generateMutation.isPending || previewMutation.isPending}
                      onChange={event => toggleAll(event.target.checked)} />
                    选择全部 READY（{selectableIds.length}）
                  </label>
                  <span>已明确选择 {selectedCandidateIds.length} 项；不可选候选不会进入 Draft</span>
                </div>
                {candidates.length === 0 ? (
                  <ConsoleEmpty title="暂无 Utility 候选" description="本次只读预览未发现可执行的目录候选。" />
                ) : (
                  <ResponsiveDataView
                    desktop={<div className="nfc-v2-utility-table-scroll">
                      <table className="nfc-v2-utility-table">
                        <thead><tr>
                          <th scope="col">选择</th><th scope="col">状态</th>
                          <th scope="col">包装目录 B</th><th scope="col">唯一子项 C</th>
                          <th scope="col">移动目标 A/C</th>
                        </tr></thead>
                        <tbody>{candidates.map(candidate => (
                          <tr key={candidate.candidate_id}>
                            <td>{selectCandidate(candidate)}</td>
                            <td>{candidateStatus(candidate)}</td>
                            <td><CodePath value={candidate.wrapper_path} /></td>
                            <td><div className="nfc-inline-badges">
                              {candidate.child_object_type &&
                                <span className="nfc-kind-badge">{candidate.child_object_type.toUpperCase()}</span>}
                              <CodePath value={candidate.child_path} muted={!candidate.child_path} />
                            </div></td>
                            <td><CodePath value={candidate.target_path} muted={!candidate.target_path} /></td>
                          </tr>
                        ))}</tbody>
                      </table>
                    </div>}
                    mobile={<div className="nfc-mobile-record-list nfc-v2-utility-mobile">
                      {candidates.map(candidate => (
                        <article className="nfc-utility-candidate-mobile-card" key={candidate.candidate_id}>
                          <div className="nfc-mobile-record-heading">
                            <label className="nfc-quarantine-mobile-id">
                              {selectCandidate(candidate)}
                              <span className="nfc-mono">{candidate.candidate_id}</span>
                            </label>
                            {candidateStatus(candidate)}
                          </div>
                          <div className="nfc-plan-item-paths">
                            <div className="nfc-plan-item-path-row"><span>Wrapper B</span>
                              <CodePath value={candidate.wrapper_path} /></div>
                            <div className="nfc-plan-item-path-row"><span>
                              Child C{candidate.child_object_type ? ' · ' + candidate.child_object_type.toUpperCase() : ''}
                            </span><CodePath value={candidate.child_path} muted={!candidate.child_path} /></div>
                            <div className="nfc-plan-item-path-row"><span>Target</span>
                              <CodePath value={candidate.target_path} muted={!candidate.target_path} /></div>
                          </div>
                          {!candidate.selectable && <p className="nfc-mobile-record-note">
                            此候选不可选择，不会进入 Draft。
                          </p>}
                        </article>
                      ))}
                    </div>}
                  />
                )}
              </>
            )}
          </>
        )}
      </div>
      <ConsoleConfirmDialog
        open={confirmation !== null}
        onOpenChange={next => { if (!next && !draftBusy && !draftInFlight.current) setConfirmation(null); }}
        title="确认生成 Utility 计划草稿？"
        description={<div className="nfc-v2-utility-confirm">
          <p>仅提交本次 Preview 中 READY 且明确勾选的 candidate_id。</p>
          <p>候选数：{confirmation?.selected_candidate_ids?.length ?? 0}</p>
          <p>Generate 只生成新的 Draft Plan；后续仍需 Freeze → Validate → Execute。</p>
          <p>若预览摘要失效（PREVIEW_CHANGED），必须重新 Preview。</p>
        </div>}
        confirmText="生成草稿"
        danger={false}
        busy={draftBusy || generateMutation.isPending}
        disabled={!canDraft || !sameUtilityDraftRequest(confirmation, requestNow)}
        onConfirm={() => { void handleGenerate(); }}
      />
    </DataPanel>
  );
};
