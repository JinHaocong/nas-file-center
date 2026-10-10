import React, { useReducer, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { DedupeActionDialog, type DedupeNoticeKind } from '../../components/dedupe/DedupeActionDialog';
import { scansApi, storageOptimizationApi } from '../../api/domain';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import {
  DedupeScorerConfig,
  DirectDedupePreviewResponse,
  DedupePreviewMemberRow,
  DedupeStorageAction,
} from '../../types/dedupe';
import {
  createDefaultDedupeScorerConfig,
  isScorerConfigDirty,
  validateScorerConfigForm,
} from '../../utils/dedupeConfig';
import {
  dedupeStateReducer,
  initialDedupeState,
  canGeneratePlan,
} from '../../utils/dedupeState';
import {
  DedupeScorerConfigEditor,
  DedupePreviewTable,
  DedupePreviewSummaryPanel,
  DedupeExplainDrawer,
  DedupeIdentitySafetyPanel,
  DedupeStorageActionPanel,
} from '../../components/dedupe';
import { formatBytes } from '../../utils/format';
import { shouldAcceptDirectResponse } from '../../utils/hotfix2Helpers';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { CodePath } from '../../components/ui/CodePath';
import { useAuth } from '../../contexts/AuthContext';

const parentDirectory = (path: string): string => {
  const normalized = path.replace(/\/+$/, '');
  const index = normalized.lastIndexOf('/');
  if (index <= 0) return '/';
  return normalized.slice(0, index);
};

export const AdvancedDedupePage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const scanId = parseInt(id || '0', 10);
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const toast = useConsoleToast();
  const generateInFlight = useRef(false);
  const [notice, setNotice] = useState<DedupeNoticeKind | null>(null);
  const [noticeError, setNoticeError] = useState<string | null>(null);

  const [dedupeState, dispatch] = useReducer(dedupeStateReducer, initialDedupeState);
  const [scorerConfig, setScorerConfig] = useState<DedupeScorerConfig>(
    createDefaultDedupeScorerConfig()
  );
  const [previewedConfig, setPreviewedConfig] = useState<DedupeScorerConfig | null>(null);
  const [storageAction, setStorageAction] = useState<DedupeStorageAction>('quarantine');
  const [previewedStorageAction, setPreviewedStorageAction] = useState<DedupeStorageAction | null>(null);
  const [previewData, setPreviewData] = useState<DirectDedupePreviewResponse | null>(null);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(50);
  const [selectedMember, setSelectedMember] = useState<DedupePreviewMemberRow | null>(null);
  const [explainOpen, setExplainOpen] = useState<boolean>(false);

  const {
    data: scan,
    isLoading: scanLoading,
    error: scanError,
  } = useQuery({
    queryKey: ['scanDetail', scanId],
    queryFn: () => scansApi.getScanDetail(scanId),
    enabled: !!scanId,
  });

  const diagnosticRow =
    previewData?.storage_action === storageAction
      ? previewData.rows.find(
    (row) =>
      row.group_status === 'actionable' &&
      Boolean(row.group_recommended_keep_path) &&
      row.absolute_path !== row.group_recommended_keep_path
        )
      : undefined;
  const diagnosticPair =
    diagnosticRow && diagnosticRow.group_recommended_keep_path
      ? {
          keepPath: diagnosticRow.group_recommended_keep_path,
          sourcePath: diagnosticRow.absolute_path,
          keepParent: parentDirectory(diagnosticRow.group_recommended_keep_path),
          sourceParent: parentDirectory(diagnosticRow.absolute_path),
        }
      : null;

  const capabilityMutation = useMutation({
    mutationFn: () => {
      if (!diagnosticPair) {
        throw new Error('当前预览页没有可用于能力探测的 KEEP / SOURCE 路径对');
      }
      return storageOptimizationApi.probeCapabilities({
        source_directory: diagnosticPair.keepParent,
        destination_directory: diagnosticPair.sourceParent,
      });
    },
    onSuccess: () => toast.success('运行时能力探测完成；Validate / Execute 仍会重新验证'),
    onError: (err: any) => toast.error(err?.message || '运行时能力探测失败'),
  });

  const handleConfigChange = (newConfig: DedupeScorerConfig) => {
    setNotice(null); // Any pending confirmation refers to the old preview digest.
    setScorerConfig(newConfig);
    capabilityMutation.reset();
    dispatch({ type: 'CONFIG_EDITED' });
  };

  const handleStorageActionChange = (nextAction: DedupeStorageAction) => {
    setNotice(null); // Invalidate stale action confirmation.
    setStorageAction(nextAction);
    capabilityMutation.reset();
    dispatch({ type: 'CONFIG_EDITED' });
  };

  interface PreviewMutationVariables {
    cfg: DedupeScorerConfig;
    generation: number;
    page: number;
    pageSize: number;
    storageAction: DedupeStorageAction;
  }

  const previewMutation = useMutation({
    mutationFn: (variables: PreviewMutationVariables) =>
      scansApi.dedupePreview(scanId, {
        scorer_config: variables.cfg,
        storage_action: variables.storageAction,
        page: variables.page,
        page_size: variables.pageSize,
      }),
    onSuccess: (data, variables) => {
      if (
        !shouldAcceptDirectResponse({
          responseGeneration: variables.generation,
          currentGeneration: dedupeState.configGeneration,
        })
      ) {
        return;
      }
      setPage(variables.page);
      setPageSize(variables.pageSize);
      setPreviewData(data);
      setPreviewedConfig(JSON.parse(JSON.stringify(variables.cfg)));
      setPreviewedStorageAction(variables.storageAction);
      capabilityMutation.reset();
      dispatch({
        type: 'PREVIEW_SUCCESS',
        digest: data.preview_digest,
        requestGeneration: variables.generation,
      });
      toast.success('高级预览计算完成');
    },
    onError: (err: any) => {
      const formatted = formatDedupeErrorMessage(err);
      dispatch({ type: 'PREVIEW_FAILED', error: formatted });
      toast.error(formatted);
    },
  });

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!previewData || !previewedConfig || !previewedStorageAction ||
          !dedupeState.acceptedPreviewDigest) {
        throw new Error('无有效的权威预览数据，请先运行预览');
      }
      return scansApi.createAdvancedDedupePlan(scanId, {
        scorer_config: previewedConfig,
        expected_preview_digest: dedupeState.acceptedPreviewDigest,
        storage_action: previewedStorageAction,
      });
    },
    onSuccess: (res) => {
      generateInFlight.current = false;
      setNotice(null);
      dispatch({ type: 'GENERATE_SUCCESS' });
      toast.success('成功生成精确去重计划 #' + (res.id || res.plan_id));
      navigate('/plans/' + (res.id || res.plan_id));
    },
    onError: (err: any) => {
      generateInFlight.current = false;
      const structured = getStructuredApiError(err);
      const formatted = formatDedupeErrorMessage(err);
      setNoticeError(formatted);
      if (structured.code === 'PREVIEW_CHANGED' ||
          structured.code === 'DEDUPE_PREVIEW_CHANGED') {
        dispatch({ type: 'PREVIEW_CHANGED_ERROR', error: formatted });
        setNotice('preview_changed');
        return;
      }
      dispatch({ type: 'GENERATE_FAILED', error: formatted });
      if (structured.code === 'DEDUPE_SCAN_NOT_FOUND') {
        setNotice('scan_not_found');
      } else if (structured.code === 'DEDUPE_SCAN_NOT_COMPLETED') {
        setNotice('scan_not_completed');
      } else if (structured.code === 'DEDUPE_EMPTY_PLAN') {
        setNotice('empty_plan');
      } else {
        setNotice(null);
        toast.error(formatted);
      }
    },
  });

  const isDirty =
    dedupeState.status === 'PREVIEW_STALE' ||
    dedupeState.acceptedPreviewDigest === null ||
    previewedStorageAction !== storageAction ||
    (previewedConfig ? isScorerConfigDirty(scorerConfig, previewedConfig) : true);

  const validation = validateScorerConfigForm(scorerConfig);

  const handleRunPreview = () => {
    if (!validation.valid) {
      toast.error('请先修正配置校验错误');
      return;
    }
    const currentGen = dedupeState.configGeneration;
    dispatch({ type: 'PREVIEW_STARTED' });
    previewMutation.mutate({
      cfg: scorerConfig,
      generation: currentGen,
      page: 1,
      pageSize,
      storageAction,
    });
  };

  const handleConfirmGeneratePlan = () => {
    if (generateInFlight.current || generateMutation.isPending ||
        previewMutation.isPending || !canGeneratePlan(dedupeState) ||
        isDirty || !previewData || previewData.planned_action_count === 0) return;
    setNoticeError(null);
    setNotice('generate');
  };

  const handleNoticeConfirm = () => {
    if (notice === 'generate') {
      // Confirm with the *latest* state, never the snapshot captured when dialog opened.
      if (generateInFlight.current || generateMutation.isPending ||
          previewMutation.isPending || !canGeneratePlan(dedupeState) ||
          isDirty || !previewData || previewData.planned_action_count === 0) {
        setNotice(null);
        return;
      }
      generateInFlight.current = true;
      dispatch({ type: 'GENERATE_STARTED' });
      generateMutation.mutate();
    } else if (notice === 'preview_changed') {
      setNotice(null);
      handleRunPreview();
    } else if (notice === 'scan_not_found') {
      setNotice(null);
      navigate('/scans');
    } else if (notice === 'scan_not_completed') {
      setNotice(null);
      navigate('/scans/' + scanId);
    } else {
      setNotice(null);
    }
  };

  const handlePageChange = (newPage: number, newPageSize: number) => {
    const currentGen = dedupeState.configGeneration;
    dispatch({ type: 'PREVIEW_STARTED' });
    previewMutation.mutate({
      cfg: scorerConfig,
      generation: currentGen,
      page: newPage,
      pageSize: newPageSize,
      storageAction,
    });
  };

  const handleSelectMember = (member: DedupePreviewMemberRow) => {
    setSelectedMember(member);
    setExplainOpen(true);
  };

  if (scanLoading) {
    return (
      <div className="nfc-v2-dedupe-page-state" role="status" aria-live="polite">
        <span className="nfc-console-spinner" aria-hidden="true" />
        正在加载扫描任务…
      </div>
    );
  }

  if (scanError || !scan) {
    return (
      <section className="nfc-v2-dedupe-page-state" role="alert">
        <h2>扫描任务不存在</h2>
        <p>未找到 ID 为 #{scanId} 的扫描任务</p>
        <ConsoleButton onClick={() => navigate('/scans')}>返回扫描列表</ConsoleButton>
      </section>
    );
  }

  if (scan.status !== 'completed') {
    return (
      <section className="nfc-v2-dedupe-page-state" role="alert">
        <h2>扫描任务尚未完成</h2>
        <p>扫描任务当前状态为 {scan.status}，只有已完成的扫描才能进行高级去重分析。</p>
        <ConsoleButton onClick={() => navigate('/scans/' + scanId)}>返回扫描详情</ConsoleButton>
      </section>
    );
  }

  if (scan.total_groups === 0) {
    return (
      <section className="nfc-v2-dedupe-page-state" role="status">
        <h2>未发现重复文件</h2>
        <p>本次扫描未发现任何重复文件组，无需执行去重。</p>
        <ConsoleButton onClick={() => navigate('/scans/' + scanId)}>返回扫描详情</ConsoleButton>
      </section>
    );
  }

  const scanSummary = [
    { label: '扫描任务', value: scan.name },
    { label: '重复组', value: `${scan.total_groups.toLocaleString()} 组`, emphasis: true },
    {
      label: '重复文件',
      value: `${scan.total_files_in_groups.toLocaleString()} 个`,
      emphasis: true,
    },
    {
      label: '预估可释放',
      value: formatBytes(scan.reclaimable_bytes),
      emphasis: true,
    },
  ];

  return (
    <div className="nfc-operations-page nfc-dedupe-stage-stack nfc-advanced-dedupe-page nfc-page-layout-workbench">
      <PageHeader
        title="高级精确去重"
        description={
          <div className="nfc-plan-header-meta">
            <span className="nfc-mono">Scan #{scanId}</span>
            <StatusBadge status={scan.status} />
            <span>只读评分预览 → Draft；Preview 本身不会修改文件系统。</span>
          </div>
        }
        actions={
          <ActionBar compact>
            <ConsoleButton onClick={() => navigate('/scans/' + scanId)}>
              返回扫描详情
            </ConsoleButton>
          </ActionBar>
        }
      />

      <div className="nfc-dedupe-cockpit">
        <div className="nfc-dedupe-context-rail">
          <DataPanel
        title="扫描上下文"
        description="高级去重基于此已完成扫描快照进行评分和选择。"
        className="nfc-panel-flush"
      >
        <ResponsiveDescriptions items={scanSummary} />
        <div className="nfc-root-list">
          <span className="nfc-root-list-label">扫描根目录</span>
          <div className="nfc-root-list-values">
            {scan.roots.map((root, idx) => (
              <CodePath value={root} key={idx} />
            ))}
          </div>
        </div>
          </DataPanel>
        </div>

        <div className="nfc-dedupe-strategy-stage">
          <DataPanel
            title="1. 存储动作"
            description="Quarantine 保持默认；Hardlink / Reflink 需要显式选择，且任何动作变化都会使已有 Preview 失效。"
          >
            <DedupeStorageActionPanel
              value={storageAction}
              onChange={handleStorageActionChange}
              disabled={previewMutation.isPending || generateMutation.isPending}
              isAdmin={isAdmin}
              diagnosticPair={diagnosticPair}
              capabilityData={capabilityMutation.data}
              capabilityLoading={capabilityMutation.isPending}
              capabilityError={(capabilityMutation.error as any)?.message || null}
              onProbeCapabilities={() => capabilityMutation.mutate()}
            />
          </DataPanel>

          <DataPanel
        title="2. 评分策略与偏好配置"
        description="所有配置变化都会使已接受的 preview digest 失效，必须重新 Preview。"
      >
        <div className="nfc-dedupe-editor-wrap">
          <DedupeScorerConfigEditor
            value={scorerConfig}
            onChange={handleConfigChange}
            disabled={previewMutation.isPending || generateMutation.isPending}
          />
        </div>

        <ActionBar className="nfc-dedupe-config-actions">
          <ActionBar compact>
            <ConsoleButton variant="primary"
              leadingIcon={<ConsoleIcon name="zap" size={16} />}
              onClick={handleRunPreview} loading={previewMutation.isPending}
              disabled={!validation.valid || generateMutation.isPending}>
              运行高级预览 (Preview)
            </ConsoleButton>
            {isDirty && (
              <span className="nfc-status-badge nfc-status-warning">
                <span className="nfc-status-dot" />
                配置已修改，需重新运行预览
              </span>
            )}
          </ActionBar>
          <span className="nfc-dedupe-config-note">
            服务端只读计算权威预览；不会创建 BatchPlan，也不会修改真实文件。
          </span>
        </ActionBar>
          </DataPanel>
        </div>
      </div>

      {previewData && (
        <>
          <DedupeIdentitySafetyPanel
            authorityDigest={previewData.preview_digest}
            authorityType="preview_digest"
            previewSource={previewData.preview_source}
            liveFilesystemVerified={previewData.live_filesystem_verified}
            scorerConfigDigest={previewData.scorer_config_digest}
            sourceSnapshotDigest={previewData.source_snapshot_digest}
            decisionDigest={previewData.decision_digest}
            engineVersion={previewData.dedupe_engine_version}
            effectiveSafetyPolicy={
              previewData.effective_safety_policy ||
              previewData.summary?.effective_safety_policy
            }
          />

          <DedupePreviewSummaryPanel
            summary={{
              ...(previewData.summary || previewData),
              effective_safety_policy: previewData.effective_safety_policy,
            }}
            effectiveSafetyPolicy={previewData.effective_safety_policy}
            scanRoots={previewData.scan_roots || scan.roots}
            selectionMode={previewData.selection_mode}
          />

          <section
            className={`nfc-dedupe-plan-surface ${
              isDirty ? 'nfc-dedupe-plan-surface-stale' : 'nfc-dedupe-plan-surface-ready'
            }`}
          >
            <ActionBar>
              <div className="nfc-dedupe-plan-copy">
                <strong>3. 确认并生成执行计划草案</strong>
                <span>
                  {isDirty
                    ? '当前 preview_digest 对应旧配置；必须重新 Preview 后才能生成计划。'
                    : '提交当前 acceptedPreviewDigest / expected_preview_digest，原子创建 Draft。Draft 之后仍需 Freeze -> Validate -> Execute。'}
                </span>
              </div>
              <ActionBar compact>
                {isDirty && (
                  <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
                    onClick={handleRunPreview} loading={previewMutation.isPending}
                    disabled={generateMutation.isPending}>
                    重新运行预览
                  </ConsoleButton>
                )}
                <ConsoleButton variant="primary"
                  leadingIcon={<ConsoleIcon name="calendar" size={16} />}
                  onClick={handleConfirmGeneratePlan}
                  loading={generateMutation.isPending}
                  disabled={
                    !canGeneratePlan(dedupeState) || isDirty ||
                    previewMutation.isPending ||
                    previewData.planned_action_count === 0
                  }>
                  生成执行计划草案
                </ConsoleButton>
              </ActionBar>
            </ActionBar>
          </section>

          <DataPanel
            title="去重候选与 Storage Action 决策"
            description="每个成员的 KEEP / QUARANTINE / HARDLINK / REFLINK、metadata eligibility 与阻断原因都可追溯解释。"
            action={<span className="nfc-panel-count">{previewData.total_rows} candidates</span>}
            className="nfc-panel-flush"
            variant="dense"
          >
            <DedupePreviewTable
              rows={previewData.rows}
              loading={previewMutation.isPending}
              scanRoots={previewData.scan_roots || scan.roots}
              onSelectMember={handleSelectMember}
              pagination={{
                current: page,
                pageSize,
                total: previewData.total_rows,
                onChange: handlePageChange,
              }}
            />
          </DataPanel>
        </>
      )}

      <DedupeExplainDrawer
        open={explainOpen}
        onClose={() => setExplainOpen(false)}
        member={selectedMember}
        groupMembers={previewData?.rows || []}
      />
      <DedupeActionDialog
        kind={notice}
        storageAction={storageAction}
        errorMessage={noticeError}
        busy={generateMutation.isPending || generateInFlight.current}
        onCancel={() => {
          if (!generateMutation.isPending && !generateInFlight.current) setNotice(null);
        }}
        onConfirm={handleNoticeConfirm}
      />
    </div>
  );
};
