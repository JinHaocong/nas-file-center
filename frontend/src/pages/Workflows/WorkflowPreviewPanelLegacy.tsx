import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { indexesApi } from '../../api/domain';
import type { IndexRoot } from '../../types';
import { getStructuredApiError, formatDedupeErrorMessage } from '../../api/errors';
import type { WorkflowPreviewItem, WorkflowPreviewResponse, WorkflowMode, WorkflowGeneratePlanRequest } from '../../types/workflow';
import type { DedupeSummary, DedupePreviewMemberRow } from '../../types/dedupe';
import { WorkflowPreviewState, transitionPreviewState } from '../../utils/workflowPreviewMachine';
import { canPreviewWorkflow, canGenerateDraft } from '../../utils/workflowRbac';
import { normalizeSelectedRoots } from '../../utils/rootCardinality';
import { computePreviewRowIndex } from '../../utils/workflowRevisionParser';
import { CompletedScanPicker } from '../../components/workflows/CompletedScanPicker';
import { mapWorkflowPreviewItemsToDedupeRows } from '../../utils/dedupePreview';
import { computeWorkflowDedupeTableTotal, shouldAcceptWorkflowResponse, computeCanDraft } from '../../utils/hotfix2Helpers';
import { buildLegacyDraftRequest, sameLegacyDraftRequest } from '../../utils/workflowLegacyDraft';
import { DedupeIdentitySafetyPanel, DedupePreviewSummaryPanel, DedupePreviewTable, DedupeExplainDrawer } from '../../components/dedupe';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

export interface PreviewRequestSnapshot {
  workflowId: number;
  revision: number;
  mode: WorkflowMode;
  page: number;
  pageSize: number;
  onlyChanged: boolean;
  scanJobId?: number;
  roots?: number[];
  requestId: number;
}

interface WorkflowPreviewPanelProps {
  workflowId: number;
  revision: number;
  mode?: WorkflowMode;
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const WorkflowPreviewPanel: React.FC<WorkflowPreviewPanelProps> = ({
  workflowId,
  revision,
  mode = "file",
  isDirty,
  isArchived = false,
  onGeneratePlanSuccess,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const liveContext = useRef({ workflowId, revision, mode, isDirty, isArchived });
  liveContext.current = { workflowId, revision, mode, isDirty, isArchived };
  const generating = useRef(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<WorkflowGeneratePlanRequest | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [selectedRoots, setSelectedRoots] = useState<number[] | undefined>(undefined);
  const [selectedScanJobId, setSelectedScanJobId] = useState<number | undefined>(undefined);
  const [onlyChanged, setOnlyChanged] = useState<boolean>(false);
  const [customPlanName, setCustomPlanName] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Explain drawer state for dedupe mode
  const [selectedDedupeMember, setSelectedDedupeMember] = useState<DedupePreviewMemberRow | null>(null);
  const [explainOpen, setExplainOpen] = useState(false);

  const isOrganizer = mode === "organizer";
  const isDedupe = mode === "dedupe";

  const [previewState, setPreviewState] = useState<WorkflowPreviewState>(
    isDirty ? "EDITING_DIRTY" : "SAVED_PREVIEW_REQUIRED"
  );
  const [previewData, setPreviewData] = useState<WorkflowPreviewResponse | null>(null);
  const latestRequestIdRef = useRef<number>(0);
  const [previewContext, setPreviewContext] = useState<string | null>(null);
  const contextKey = [workflowId, revision, mode, Number(isDirty), Number(isArchived)].join(':');

  const { data: indexesData } = useQuery({
    queryKey: ["indexesRootsList"],
    queryFn: async () => {
      const res = await indexesApi.listIndexes(1, 100);
      return res.items;
    },
    enabled: !isDedupe,
  });
  const scanRoots: IndexRoot[] = indexesData || [];

  useEffect(() => {
    setPreviewState((prev) => transitionPreviewState(prev, { type: "DIRTY_CHANGE", isDirty }));
    if (isDirty) {
      latestRequestIdRef.current += 1;
      setPreviewData(null);
      setPreviewContext(null);
      setConfirmation(null);
    }
  }, [isDirty]);

  useEffect(() => {
    latestRequestIdRef.current += 1;
    setSelectedRoots(undefined);
    setSelectedScanJobId(undefined);
    setPreviewData(null);
    setPreviewContext(null);
    setConfirmation(null);
    setPreviewState(isDirty ? "EDITING_DIRTY" : "SAVED_PREVIEW_REQUIRED");
  }, [mode, workflowId, revision, isArchived]);

  const previewMutation = useMutation({
    mutationFn: async (snapshot: PreviewRequestSnapshot) => {
      if (!snapshot.workflowId || isDirty || isArchived) {
        throw new Error("当前状态无法执行工作流预览");
      }
      if (snapshot.mode === "dedupe") {
        if (!snapshot.scanJobId) {
          throw new Error("请先选择已完成的扫描任务");
        }
        return workflowApi.previewWorkflow(snapshot.workflowId, {
          revision: snapshot.revision,
          page: snapshot.page,
          page_size: snapshot.pageSize,
          only_changed: snapshot.onlyChanged,
          runtime_inputs: {
            scan_job_id: snapshot.scanJobId,
          },
        });
      }

      return workflowApi.previewWorkflow(snapshot.workflowId, {
        revision: snapshot.revision,
        page: snapshot.page,
        page_size: snapshot.pageSize,
        only_changed: snapshot.onlyChanged,
        runtime_inputs:
          snapshot.roots && snapshot.roots.length > 0
            ? { root_ids: snapshot.roots }
            : undefined,
      });
    },
    onMutate: () => {
      setPreviewError(null);
      setErrorMessage(null);
      setPreviewState((prev) => transitionPreviewState(prev, { type: "START_PREVIEW" }));
    },
    onSuccess: (data, variables) => {
      if (!shouldAcceptWorkflowResponse({
        snapshot: variables,
        currentWorkflowId: liveContext.current.workflowId,
        currentRevision: liveContext.current.revision,
        currentMode: liveContext.current.mode,
        currentRequestId: latestRequestIdRef.current,
      })) {
        return;
      }
      if (liveContext.current.isDirty || liveContext.current.isArchived ||
          data.workflow_id !== variables.workflowId ||
          (data.workflow_revision ?? data.revision) !== variables.revision) {
        setPreviewData(null); setPreviewContext(null);
        setPreviewError('预览版本与工作流不一致，请重新 Preview');
        setPreviewState('PREVIEW_STALE');
        return;
      }
      setPreviewContext([variables.workflowId, variables.revision, variables.mode, 0, 0].join(':'));
      setPage(variables.page);
      setPageSize(variables.pageSize);
      setPreviewData(data);
      setPreviewState((prev) =>
        transitionPreviewState(prev, {
          type: "PREVIEW_SUCCESS",
          compileDigest: data.compile_digest,
        })
      );
    },
    onError: (err, variables) => {
      if (!shouldAcceptWorkflowResponse({
        snapshot: variables,
        currentWorkflowId: liveContext.current.workflowId,
        currentRevision: liveContext.current.revision,
        currentMode: liveContext.current.mode,
        currentRequestId: latestRequestIdRef.current,
      })) {
        return;
      }
      const formatted = formatDedupeErrorMessage(err);
      setPreviewError(formatted);
      setPreviewData(null);
      setPreviewContext(null);
      setPreviewState((prev) =>
        transitionPreviewState(prev, {
          type: "PREVIEW_ERROR",
          message: formatted,
        })
      );
    },
  });

  const triggerPreview = (params?: {
    page?: number;
    pageSize?: number;
    onlyChanged?: boolean;
    scanJobId?: number;
    roots?: number[];
  }) => {
    const p = params?.page ?? page;
    const ps = params?.pageSize ?? pageSize;
    const oc = params?.onlyChanged !== undefined ? params.onlyChanged : onlyChanged;
    const sid = params?.scanJobId !== undefined ? params.scanJobId : selectedScanJobId;
    const rts = params?.roots !== undefined ? params.roots : selectedRoots;

    if (!canPreviewWorkflow(isArchived) || isDirty || generating.current ||
        previewMutation.isPending || generatePlanMutation.isPending || draftBusy) return;
    setPreviewData(null); setPreviewContext(null); setConfirmation(null);
    const reqId = ++latestRequestIdRef.current;
    previewMutation.mutate({
      workflowId,
      revision,
      mode,
      page: p,
      pageSize: ps,
      onlyChanged: oc,
      scanJobId: sid,
      roots: rts,
      requestId: reqId,
    });
  };

  const handleRootsChange = (roots: number[] | undefined) => {
    latestRequestIdRef.current += 1;
    const normalized = normalizeSelectedRoots(roots, mode as any);
    setSelectedRoots(normalized);
    setPage(1);
    setPreviewState((prev) => transitionPreviewState(prev, { type: "ROOTS_CHANGE" }));
    setPreviewData(null); setPreviewContext(null); setConfirmation(null);
  };

  const handleScanJobChange = (scanJobId?: number) => {
    latestRequestIdRef.current += 1;
    setSelectedScanJobId(scanJobId);
    setPage(1);
    setPreviewState("SAVED_PREVIEW_REQUIRED");
    setPreviewData(null); setPreviewContext(null); setConfirmation(null);
  };

  const generatePlanMutation = useMutation({
    mutationFn: ({ targetId, snapshot }: { targetId: number; snapshot: WorkflowGeneratePlanRequest }) =>
      workflowApi.generatePlan(targetId, snapshot),
  });

  const acceptedPreview = previewContext === contextKey && !isDirty && !isArchived
    ? previewData : null;

  // Mapped dedupe rows if mode is dedupe
  const dedupeRows = useMemo(() => {
    if (!isDedupe || !acceptedPreview?.items) return [];
    return mapWorkflowPreviewItemsToDedupeRows(previewData.items);
  }, [isDedupe, acceptedPreview?.items]);

  // Directly consume dedupe_summary from previewData (Blocker 1)




  const organizerItemStage = (item: WorkflowPreviewItem) => {
    if (!organizerAdvanced) return "Standard";
    if (item.metadata?.conflict) return "Blocking conflict";
    if (item.metadata?.proposal_type === "wrapper_collapse") return "Stage A";
    return organizerStructuralRequired ? "Stage B · locked" : "Stage B";
  };

  const organizerRuleLabel = (item: WorkflowPreviewItem) => {
    const proposalType = String(item.metadata?.proposal_type || "");
    const labels: Record<string, string> = {
      wrapper_collapse: "Wrapper collapse",
      directory_rename: "Directory rename",
      file_rename: "File numbering",
      latest_child_prefix: "Latest prefix",
      touch: "mtime",
    };
    return labels[proposalType] || proposalType || item.operation;
  };

  const canPreview = canPreviewWorkflow(isArchived) && !isDirty &&
    (!isDedupe || Boolean(selectedScanJobId));
  const dedupeSummary: DedupeSummary | null = isDedupe ? (acceptedPreview?.dedupe_summary ?? null) : null;
  const organizerSummary = isOrganizer ? acceptedPreview?.organizer_summary : null;
  const organizerAdvanced = Boolean(organizerSummary?.advanced_enabled);
  const organizerStructuralRequired = Boolean(organizerSummary?.structural_required);
  const organizerPreviewDigest = organizerSummary?.preview_digest || undefined;
  const organizerConflicts = Number(organizerSummary?.summary?.conflicts ?? 0);
  const canDraft = canGenerateDraft(isArchived) && computeCanDraft({
    isArchived, isDirty, previewState, compileDigest: acceptedPreview?.compile_digest,
    previewPending: previewMutation.isPending,
    generatePending: generatePlanMutation.isPending || draftBusy,
    isDedupe, selectedScanJobId,
    hasDedupeSummary: Boolean(acceptedPreview?.dedupe_summary),
  }) && (!organizerAdvanced || (Boolean(organizerPreviewDigest) && organizerConflicts === 0));
  const currentDraft = buildLegacyDraftRequest({
    preview: acceptedPreview, workflowId, revision, mode, selectedRoots, selectedScanJobId,
    planName: customPlanName, ready: canDraft,
  });
  const organizerItemStage = (item: WorkflowPreviewItem) => {
    if (!organizerAdvanced) return 'Standard';
    if (item.metadata?.conflict) return 'Blocking conflict';
    if (item.metadata?.proposal_type === 'wrapper_collapse') return 'Stage A';
    return organizerStructuralRequired ? 'Stage B · locked' : 'Stage B';
  };
  const organizerRuleLabel = (item: WorkflowPreviewItem) => {
    const labels: Record<string, string> = {
      wrapper_collapse: 'Wrapper collapse', directory_rename: 'Directory rename',
      file_rename: 'File numbering', latest_child_prefix: 'Latest prefix', touch: 'mtime',
    };
    const proposalType = String(item.metadata?.proposal_type || '');
    return labels[proposalType] || proposalType || item.operation;
  };
  const toggleRoot = (id: number, checked: boolean) => {
    if (isDirty || isArchived || previewMutation.isPending || draftBusy ||
        generatePlanMutation.isPending || !Number.isSafeInteger(id) ||
        !scanRoots.some(root => root.id === id)) return;
    const updated = checked
      ? [...new Set([...(selectedRoots || []), id])]
      : (selectedRoots || []).filter(root => root !== id);
    if (updated.length > 16) return;
    handleRootsChange(updated.length ? updated : undefined);
  };
  const navigatePage = (nextPage: number, nextSize: number) => {
    if (previewState === 'PREVIEW_READY' && !previewMutation.isPending &&
        !draftBusy && !generatePlanMutation.isPending) {
      triggerPreview({ page: nextPage, pageSize: nextSize });
    }
  };
  const draftConfirmation = () => {
    if (canDraft && currentDraft && !draftBusy) setConfirmation(currentDraft);
  };
  const submitDraft = async () => {
    if (generationInFlight.current || !canDraft ||
        !sameLegacyDraftRequest(confirmation, currentDraft) || !confirmation) {
      setConfirmation(null);
      return;
    }
    const origin = contextKey;
    const snapshot: WorkflowGeneratePlanRequest = {
      ...confirmation,
      runtime_inputs: confirmation.runtime_inputs
        ? {
            ...confirmation.runtime_inputs,
            root_ids: confirmation.runtime_inputs.root_ids
              ? [...confirmation.runtime_inputs.root_ids] : undefined,
          }
        : undefined,
    };
    generationInFlight.current = true;
    setDraftBusy(true);
    setErrorMessage(null);
    try {
      const data = await generatePlanMutation.mutateAsync({ targetId: workflowId, snapshot });
      const current = liveContext.current;
      if (origin !== [current.workflowId, current.revision, current.mode,
        Number(current.isDirty), Number(current.isArchived)].join(':')) return;
      const stageMessage = isOrganizer && acceptedPreview?.organizer_summary?.advanced_enabled
        ? acceptedPreview.organizer_summary.structural_required
          ? 'Organizer Stage A 结构计划草稿 #' + data.plan_id + ' 已生成；执行后必须重新 Preview'
          : 'Organizer Stage B 重命名计划草稿 #' + data.plan_id + ' 已生成'
        : '批处理计划草稿 #' + data.plan_id + ' 生成成功';
      toast.success(stageMessage);
      void queryClient.invalidateQueries({ queryKey: ['plansList'] });
      onGeneratePlanSuccess(data.plan_id);
    } catch (err) {
      const current = liveContext.current;
      if (origin !== [current.workflowId, current.revision, current.mode,
        Number(current.isDirty), Number(current.isArchived)].join(':')) return;
      const structured = getStructuredApiError(err);
      setErrorMessage(formatDedupeErrorMessage(err));
      if (structured.code === 'PREVIEW_CHANGED' || structured.code === 'DEDUPE_PREVIEW_CHANGED') {
        setPreviewData(prev => prev ? { ...prev, compile_digest: '' } : null);
        setPreviewState(prev => transitionPreviewState(prev, { type: 'PREVIEW_CHANGED_ERROR' }));
      } else if (structured.code === 'DEDUPE_SCAN_NOT_FOUND' ||
                 structured.code === 'DEDUPE_SCAN_NOT_COMPLETED') {
        setPreviewData(null);
        setPreviewContext(null);
        setSelectedScanJobId(undefined);
        setPreviewState('SAVED_PREVIEW_REQUIRED');
      } else if (structured.code === 'WORKFLOW_ARCHIVED') {
        setPreviewData(null);
        setPreviewContext(null);
        setPreviewState('PREVIEW_STALE');
      }
    } finally {
      generationInFlight.current = false;
      setDraftBusy(false);
      setConfirmation(null);
    }
  };
  const target = (item: WorkflowPreviewItem) =>
    item.operation === 'touch'
      ? <span className="nfc-table-meta">mtime: {item.mtime_ns
          ? new Date(item.mtime_ns / 1e6).toLocaleString() : '当前时间'}</span>
      : <CodePath value={item.target_path} muted={!item.target_path} />;
  const notice = (title: string, detail: string, tone: 'info' | 'warning' | 'error' | 'success' = 'info') =>
    <div className={'nfc-v2-legacy-notice is-' + tone} role={tone === 'warning' || tone === 'error' ? 'alert' : 'note'}>
      <ConsoleIcon name={tone === 'error' ? 'alert-circle' : 'info'} size={18} />
      <div><strong>{title}</strong><p>{detail}</p></div>
    </div>;
  const previewStates: Record<string, string> = {
    EDITING_DIRTY: '配置已修改，需先保存新版本',
    SAVED_PREVIEW_REQUIRED: '待显式生成预览',
    PREVIEWING: '正在分析执行预览…',
    PREVIEW_READY: '预览已就绪 (可生成草稿)',
    PREVIEW_STALE: '预览已失效 (需重新刷新预览)',
  };

  return (
    <DataPanel title="执行预览与批处理计划生成"
      description="Preview 基于已保存 revision 与显式 runtime inputs 生成权威 compile digest；Generate 只创建 Draft。"
      className="nfc-workflow-preview-panel nfc-v2-legacy-preview"
      action={<ActionBar compact>
        <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
          disabled={!canPreview || draftBusy || generatePlanMutation.isPending}
          loading={previewMutation.isPending} onClick={() => triggerPreview()}>
          {acceptedPreview ? '刷新预览' : '生成预览'}
        </ConsoleButton>
        <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="zap" size={16} />}
          loading={draftBusy} disabled={!currentDraft || !canDraft} onClick={draftConfirmation}>
          {organizerStructuralRequired ? '生成 Stage A 结构草稿' :
            organizerAdvanced ? '生成 Stage B 重命名草稿' : '生成计划草稿'}
        </ConsoleButton>
      </ActionBar>}>
      <div className="nfc-workflow-preview-body nfc-v2-legacy-body">
        <div className="nfc-workflow-preview-state" role="status">
          <StatusBadge status={previewState === 'PREVIEW_READY' ? 'ready' :
            previewState === 'PREVIEW_STALE' ? 'stale' : 'paused'}
            label={previewStates[previewState] || previewState} />
        </div>
        {isArchived ? notice('工作流已归档',
          '归档封存的工作流只读，不允许 Preview 与 Generate。')
        : isDirty ? notice('检测到工作流定义有未保存的变动',
          '草稿未保存时禁止 Preview 与 Generate。请先保存新版本。', 'warning')
        : <>
          {errorMessage && <div className="nfc-v2-legacy-notice is-error" role="alert">
            <ConsoleIcon name="alert-circle" size={18} />
            <div><strong>操作失败</strong><p>{errorMessage}</p></div>
            <button type="button" aria-label="关闭操作错误" onClick={() => setErrorMessage(null)}>
              <ConsoleIcon name="x" size={16} />
            </button>
          </div>}
          {previewError && notice('工作流预览失败', previewError, 'error')}
          {isDedupe && acceptedPreview && !acceptedPreview.dedupe_summary &&
            notice('缺少去重权威摘要 (dedupe_summary)',
              '后端预览缺少 dedupe_summary，已禁止生成草稿。', 'error')}
          {isOrganizer && organizerAdvanced && organizerStructuralRequired &&
            notice('Organizer Stage A Structural Preview',
              'Stage B rename/file/prefix 已锁定；Stage A 执行后需 fresh Preview 获取新 digest。', 'warning')}
          {isOrganizer && organizerAdvanced && !organizerStructuralRequired && acceptedPreview &&
            notice('Organizer Stage B Rename Preview',
              '当前无结构变更，可基于 organizer preview digest 生成 Stage B 草稿。', 'success')}
          {isOrganizer && organizerConflicts > 0 &&
            notice('Organizer Preview 存在 ' + organizerConflicts + ' 个 blocking conflict',
              '冲突未清零前禁止 Generate。', 'error')}
          <div className="nfc-v2-legacy-runtime">
            {isDedupe ? <>
              <div className="nfc-v2-legacy-scan">
                <span className="nfc-form-inline-label">扫描任务</span>
                <CompletedScanPicker value={selectedScanJobId} onChange={handleScanJobChange}
                  disabled={previewMutation.isPending || draftBusy || generatePlanMutation.isPending} />
              </div>
              <label className="nfc-v2-legacy-toggle">
                <input type="checkbox" checked={onlyChanged}
                  disabled={previewMutation.isPending || draftBusy || generatePlanMutation.isPending}
                  onChange={event => {
                    const checked = event.target.checked;
                    setOnlyChanged(checked);
                    if (selectedScanJobId) triggerPreview({ page: 1, pageSize,
                      onlyChanged: checked, scanJobId: selectedScanJobId });
                    else {
                      latestRequestIdRef.current += 1;
                      setPreviewData(null);
                      setPreviewContext(null);
                      setPreviewState(prev => transitionPreviewState(prev, { type: 'ONLY_CHANGED_TOGGLE' }));
                    }
                    setConfirmation(null);
                  }} />
                仅显示将隔离项
              </label>
            </> : <fieldset className="nfc-v2-legacy-roots"
              disabled={previewMutation.isPending || draftBusy || generatePlanMutation.isPending}>
              <legend>覆盖根目录（可选）</legend>
              <p>仅允许已登记的 Index Roots；空选择表示使用步骤预设根目录。</p>
              {isOrganizer ? <select aria-label="覆盖单一根目录" className="nfc-workflow-root-select"
                value={selectedRoots?.[0] ?? ''}
                onChange={event => {
                  const id = Number(event.target.value);
                  handleRootsChange(event.target.value &&
                    scanRoots.some(root => root.id === id) ? [id] : undefined);
                }}>
                <option value="">使用步骤预设根目录</option>
                {scanRoots.map(root => <option key={root.id} value={root.id}>
                  {root.root} (ID: {root.id})
                </option>)}
              </select>
              : <div className="nfc-v2-legacy-root-options" role="group" aria-label="覆盖根目录，最多16个">
                {scanRoots.map(root => <label key={root.id}>
                  <input type="checkbox" checked={Boolean(selectedRoots?.includes(root.id))}
                    disabled={!selectedRoots?.includes(root.id) && (selectedRoots?.length ?? 0) >= 16}
                    onChange={event => toggleRoot(root.id, event.target.checked)} />
                  <CodePath value={root.root} /><span className="nfc-mono">ID: {root.id}</span>
                </label>)}
                {!scanRoots.length && <span>暂无已登记的 Index Roots</span>}
              </div>}
            </fieldset>}
            <label className="nfc-v2-legacy-plan-name">自定义计划名称（可选）
              <input type="text" placeholder="自定义计划名称 (可选)"
                className="nfc-workflow-plan-name-input" value={customPlanName}
                disabled={draftBusy || generatePlanMutation.isPending}
                onChange={event => { setCustomPlanName(event.target.value); setConfirmation(null); }} />
            </label>
          </div>
          {previewMutation.isPending && <p role="status" className="nfc-v2-legacy-loading">正在生成只读 Preview…</p>}
          {acceptedPreview && (isDedupe ?
            <div className="nfc-dedupe-stage-stack">
              <DedupeIdentitySafetyPanel
                authorityDigest={acceptedPreview.compile_digest}
                authorityType="compile_digest"
                dedupePreviewDigest={dedupeSummary?.preview_digest}
                workflowRevision={acceptedPreview.workflow_revision}
                definitionSha256={acceptedPreview.definition_sha256}
                runtimeScanJobId={selectedScanJobId}
                previewSource={acceptedPreview.preview_source}
                liveFilesystemVerified={acceptedPreview.live_filesystem_verified}
                scorerConfigDigest={dedupeSummary?.scorer_config_digest}
                sourceSnapshotDigest={dedupeSummary?.source_snapshot_digest}
                decisionDigest={dedupeSummary?.decision_digest}
                engineVersion={dedupeSummary?.dedupe_engine_version}
                effectiveSafetyPolicy={dedupeSummary?.effective_safety_policy}
              />
              {dedupeSummary && <DedupePreviewSummaryPanel summary={dedupeSummary} />}
              <section className="nfc-workflow-preview-subsection">
                <div className="nfc-workflow-preview-subheader"><div>
                  <strong>去重流水线预览明细</strong>
                  <span>当前页 {acceptedPreview.items?.length || 0} 项</span>
                </div></div>
                <DedupePreviewTable rows={dedupeRows} loading={previewMutation.isPending}
                  onSelectMember={member => { setSelectedDedupeMember(member); setExplainOpen(true); }}
                  pagination={{ current: page, pageSize,
                    total: computeWorkflowDedupeTableTotal(acceptedPreview, onlyChanged),
                    onChange: (p, ps) => navigatePage(p, ps) }} />
              </section>
              <DedupeExplainDrawer open={explainOpen} onClose={() => setExplainOpen(false)}
                member={selectedDedupeMember} groupMembers={dedupeRows} />
            </div>
          : <>
            <ResponsiveDescriptions items={[
              ...(isOrganizer && organizerAdvanced ? [
                { label: 'Organizer Stage',
                  value: organizerStructuralRequired ? 'Stage A · Structural' : 'Stage B · Rename', emphasis: true },
                { label: 'Preview Digest',
                  value: <span className="nfc-mono nfc-digest-value">
                    {organizerPreviewDigest || '(缺失，请重新 Preview)'}
                  </span> },
              ] : []),
              { label: '匹配文件/目录数', value: acceptedPreview.matched_count, emphasis: true },
              { label: '计划操作总数', value: acceptedPreview.planned_operations_count, emphasis: true },
              { label: '预览数据源', value: <span className="nfc-kind-badge">{acceptedPreview.preview_source}</span> },
              { label: 'Compile Digest', value: <span className="nfc-mono nfc-digest-value">
                {acceptedPreview.compile_digest || '(已失效，请重新生成预览)'}
              </span> },
            ]} />
            {!(acceptedPreview.items || []).length ?
              <ConsoleEmpty title="当前预览无操作项" />
            : <ResponsiveDataView
                desktop={<div className="nfc-v2-legacy-table-scroll">
                  <table className="nfc-v2-legacy-table">
                    <thead><tr>
                      <th scope="col">序号</th>
                      {isOrganizer && organizerAdvanced && <th scope="col">阶段 / 规则</th>}
                      <th scope="col">操作类型</th><th scope="col">变更状态</th>
                      <th scope="col">源文件路径</th><th scope="col">目标文件路径</th>
                    </tr></thead>
                    <tbody>{acceptedPreview.items.map((item, index) => (
                      <tr key={page + '-' + index + '-' + item.source_path + '-' + item.operation}>
                        <td>#{computePreviewRowIndex(page, pageSize, index)}</td>
                        {isOrganizer && organizerAdvanced && <td>
                          <span className="nfc-kind-badge">{organizerItemStage(item)}</span>
                          <span className="nfc-kind-badge">{organizerRuleLabel(item)}</span>
                        </td>}
                        <td><span className={'nfc-operation-badge nfc-operation-' + item.operation}>
                          {item.operation}</span></td>
                        <td><StatusBadge status={item.changed ? 'validating' : 'completed'}
                          label={item.changed ? '有变更' : '保持/更新'} /></td>
                        <td><CodePath value={item.source_path} /></td>
                        <td>{item.operation === 'touch' ?
                          <span className="nfc-table-meta">mtime: {item.mtime_ns
                            ? new Date(item.mtime_ns / 1e6).toLocaleString() : '当前时间'}</span>
                          : <CodePath value={item.target_path} muted={!item.target_path} />}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>}
                mobile={<div className="nfc-mobile-record-list nfc-v2-legacy-mobile">
                  {acceptedPreview.items.map((item, index) => (
                    <article className="nfc-workflow-preview-item-mobile-card"
                      key={page + '-' + index + '-' + item.source_path + '-' + item.operation}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-inline-badges">
                          {isOrganizer && organizerAdvanced && <>
                            <span className="nfc-kind-badge">{organizerItemStage(item)}</span>
                            <span className="nfc-kind-badge">{organizerRuleLabel(item)}</span>
                          </>}
                          <span className={'nfc-operation-badge nfc-operation-' + item.operation}>{item.operation}</span>
                          <span className="nfc-mono">#{computePreviewRowIndex(page, pageSize, index)}</span>
                        </div>
                        <StatusBadge status={item.changed ? 'validating' : 'completed'}
                          label={item.changed ? '有变更' : '保持/更新'} />
                      </div>
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row"><span>源路径</span>
                          <CodePath value={item.source_path} /></div>
                        <div className="nfc-plan-item-path-row"><span>{item.operation === 'touch' ? 'mtime' : '目标'}</span>
                          {item.operation === 'touch' ?
                            <span className="nfc-table-meta">mtime: {item.mtime_ns
                              ? new Date(item.mtime_ns / 1e6).toLocaleString() : '当前时间'}</span>
                            : <CodePath value={item.target_path} muted={!item.target_path} />}</div>
                      </div>
                    </article>
                  ))}
                </div>}
              />}
            <ConsolePagination page={page} pageSize={pageSize}
              total={acceptedPreview.planned_operations_count ?? 0}
              pageSizes={[20, 50, 100]} onChange={navigatePage} />
          </>)}
        </>}
      </div>
      <ConsoleConfirmDialog open={confirmation !== null}
        onOpenChange={next => { if (!next && !draftBusy && !generationInFlight.current) setConfirmation(null); }}
        title={organizerStructuralRequired ? '确认生成 Organizer Stage A 结构计划草稿？' :
          organizerAdvanced ? '确认生成 Organizer Stage B 重命名计划草稿？' :
          '确认基于此预览生成批处理计划草稿？'}
        description={<div className="nfc-v2-legacy-confirm">
          <p>确认当前 revision、compile digest 与显式 runtime inputs 已核对。</p>
          {organizerStructuralRequired && <p>Stage A 执行完成后必须重新 Preview 才能进入 Stage B。</p>}
          <p>Generate 只创建 Draft，后续仍需 Freeze → Validate → Execute。</p>
          <p>若服务端返回 PREVIEW_CHANGED / DEDUPE_PREVIEW_CHANGED，需要重新 Preview。</p>
        </div>}
        confirmText="生成草稿" danger={false}
        busy={draftBusy || generatePlanMutation.isPending}
        disabled={!canDraft || !sameLegacyDraftRequest(confirmation, currentDraft)}
        onConfirm={() => { void submitDraft(); }} />
    </DataPanel>
  );
};
