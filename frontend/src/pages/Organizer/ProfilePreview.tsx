import React, { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { getStructuredApiError } from '../../api/errors';
import type { OrganizerPreviewSummary, OrganizerPreviewResponse, OrganizerProfile, OrganizerProposal } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { formatBytes } from '../../utils/format';
import {
  type OrganizerPreviewFilter, canGenerateOrganizerPlan, organizerActionableChanges,
  organizerStageActionCount, organizerPreviewStageLabel, organizerProposalStageLabel,
  organizerProposalRuleLabel,
} from '../../utils/organizerPreviewSafety';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { MetricCard } from '../../components/ui/MetricCard';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

interface ProfilePreviewProps {
  profile: OrganizerProfile;
  onBack: () => void;
}

interface PreviewRequest {
  root: string;
  page: number;
  pageSize: number;
  filter: OrganizerPreviewFilter;
  snapshotId?: string;
}

/** Read-only Organizer Preview. Server remains the authority for digest-bound Plan creation. */
export const ProfilePreview: React.FC<ProfilePreviewProps> = ({ profile, onBack }) => {
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const sequenceRef = useRef(0);
  const previewInFlight = useRef(false);
  const planInFlight = useRef(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);

  const [currentRoot, setCurrentRoot] = useState(profile.root || '');
  const [previewRoot, setPreviewRoot] = useState('');
  const [rootError, setRootError] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [filterMode, setFilterMode] = useState<OrganizerPreviewFilter>('all');
  const [proposals, setProposals] = useState<OrganizerProposal[]>([]);
  const [summary, setSummary] = useState<OrganizerPreviewSummary | null>(null);
  const [totalItems, setTotalItems] = useState(0);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [snapshotId, setSnapshotId] = useState<string | undefined>();
  const [previewDigest, setPreviewDigest] = useState<string | undefined>();
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [structuralRequired, setStructuralRequired] = useState(false);

  const clearPreview = () => {
    setPreviewRoot('');
    setHasPreviewed(false);
    setProposals([]);
    setSummary(null);
    setTotalItems(0);
    setSnapshotId(undefined);
    setPreviewDigest(undefined);
    setAdvancedEnabled(false);
    setStructuralRequired(false);
  };

  useEffect(() => {
    sequenceRef.current += 1;
    previewInFlight.current = false;
    setPreviewLoading(false);
    setCurrentRoot(profile.root || '');
    setRootError(false);
    setPage(1);
    setFilterMode('all');
    clearPreview();
  }, [profile.id, profile.root]);

  const previewMutation = useMutation({
    mutationFn: (params: PreviewRequest) => organizerProfilesApi.previewProfile(profile.id, {
      root: params.root,
      page: params.page,
      page_size: params.pageSize,
      only_changed: params.filter === 'changed',
      only_conflicts: params.filter === 'conflicts',
      snapshot_id: params.snapshotId,
    }),
  });
  const planMutation = useMutation({
    mutationFn: (params: { root: string; expectedPreviewDigest?: string }) =>
      organizerProfilesApi.createPlan(profile.id, {
        root: params.root,
        include_touch: profile.mtime_mode === 'ordered',
        expected_preview_digest: params.expectedPreviewDigest,
      }),
  });

  const handleRootChange = (root: string) => {
    if (planInFlight.current) return;
    // A directory change irrevocably invalidates a previous snapshot and Plan gate.
    sequenceRef.current += 1;
    previewInFlight.current = false;
    setPreviewLoading(false);
    setCurrentRoot(root);
    setRootError(false);
    setPage(1);
    clearPreview();
  };
  const fetchPreview = async (params: PreviewRequest) => {
    if (previewInFlight.current || planInFlight.current) return;
    const root = params.root.trim();
    if (!root) {
      setRootError(true);
      toast.error('请先选择或输入整理根目录');
      return;
    }
    const requestId = ++sequenceRef.current;
    previewInFlight.current = true;
    setPreviewLoading(true);
    setRootError(false);
    try {
      const result: OrganizerPreviewResponse = await previewMutation.mutateAsync({ ...params, root });
      if (requestId !== sequenceRef.current) return;
      if (params.snapshotId && result.snapshot_id && params.snapshotId !== result.snapshot_id) {
        clearPreview();
        toast.error('预览快照发生变化，请重新执行只读 Preview');
        return;
      }
      setPreviewRoot(root);
      setProposals(result.proposals);
      setSummary(result.summary);
      setTotalItems(result.total);
      setHasPreviewed(true);
      setSnapshotId(result.snapshot_id || params.snapshotId);
      setPreviewDigest(result.preview_digest);
      setAdvancedEnabled(Boolean(result.advanced_enabled));
      setStructuralRequired(Boolean(result.structural_required));
      setFilterMode(params.filter);
      setPage(params.page);
      setPageSize(params.pageSize);
    } catch (err: unknown) {
      if (requestId === sequenceRef.current) {
        toast.error(getStructuredApiError(err).message || '预览计算失败');
      }
    } finally {
      if (requestId === sequenceRef.current) {
        previewInFlight.current = false;
        setPreviewLoading(false);
      }
    }
  };
  const handlePreviewClick = () => {
    if (planInFlight.current || previewInFlight.current) return;
    clearPreview();
    setPage(1);
    void fetchPreview({ root: currentRoot, page: 1, pageSize, filter: filterMode });
  };
  const handleFilterChange = (filter: OrganizerPreviewFilter) => {
    if (previewInFlight.current || planInFlight.current || filter === filterMode || !hasPreviewed) return;
    void fetchPreview({ root: currentRoot, page: 1, pageSize, filter, snapshotId });
  };
  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    if (previewInFlight.current || planInFlight.current || !hasPreviewed) return;
    void fetchPreview({ root: currentRoot, page: nextPage, pageSize: nextPageSize, filter: filterMode, snapshotId });
  };

  const actionableChanges = organizerActionableChanges(summary);
  const stageActionCount = organizerStageActionCount(summary, structuralRequired);
  const previewStageLabel = organizerPreviewStageLabel(advancedEnabled, structuralRequired);
  const busy = previewLoading || planLoading || previewInFlight.current || planInFlight.current;
  const canGeneratePlan = canGenerateOrganizerPlan({
    summary, advancedEnabled, structuralRequired, previewDigest,
    previewRoot, selectedRoot: currentRoot, busy,
  }, profile.mtime_mode);
  const handleGeneratePlan = async () => {
    // Recheck the current root, pending state, digest and conflict guard on click.
    if (planInFlight.current || previewInFlight.current || !canGenerateOrganizerPlan({
      summary, advancedEnabled, structuralRequired, previewDigest,
      previewRoot, selectedRoot: currentRoot, busy,
    }, profile.mtime_mode)) return;
    planInFlight.current = true;
    setPlanLoading(true);
    const requestVersion = sequenceRef.current;
    try {
      const result = await planMutation.mutateAsync({
        root: currentRoot.trim(),
        expectedPreviewDigest: advancedEnabled ? previewDigest : undefined,
      });
      if (requestVersion !== sequenceRef.current) return;
      toast.success(structuralRequired
        ? `Stage A 结构计划 #${result.id} 已生成；执行完成后必须重新 Preview 才能进入 Stage B`
        : advancedEnabled
        ? `Stage B 重命名计划 #${result.id} 已生成`
        : `已生成整理计划 #${result.id}`);
      navigate(`/plans/${result.id}`);
    } catch (err: unknown) {
      toast.error(getStructuredApiError(err).message || '生成计划失败');
    } finally {
      planInFlight.current = false;
      setPlanLoading(false);
    }
  };

  const statusForProposal = (proposal: OrganizerProposal) => {
    if (proposal.conflict) return <StatusBadge status="failed" label="冲突" />;
    if (advancedEnabled && proposal.proposal_type === 'wrapper_collapse' && proposal.changed)
      return <StatusBadge status="validating" label="Stage A" />;
    if (advancedEnabled && structuralRequired && proposal.changed)
      return <StatusBadge status="validating" label="Stage B 锁定" />;
    if (advancedEnabled && proposal.changed) return <StatusBadge status="validating" label="Stage B" />;
    if (proposal.changed) return <StatusBadge status="validating" label="需改名" />;
    return <StatusBadge status="completed" label="已规范" />;
  };
  const stageBadges = (proposal: OrganizerProposal) => (
    <div className="nfc-inline-badges">
      <span className="nfc-kind-badge">{organizerProposalStageLabel(proposal, advancedEnabled)}</span>
      <span className="nfc-kind-badge">{organizerProposalRuleLabel(proposal)}</span>
    </div>
  );
  const statsBadges = (proposal: OrganizerProposal) => (
    <div className="nfc-inline-badges">
      <span className="nfc-kind-badge">{proposal.images} P</span>
      {proposal.videos > 0 && <span className="nfc-kind-badge">{proposal.videos} V</span>}
      <span className="nfc-kind-badge">{formatBytes(proposal.total_bytes)}</span>
      {proposal.preserved_tags?.map(tag => <span key={tag} className="nfc-kind-badge">{tag}</span>)}
    </div>
  );
  const proposalStatus = (proposal: OrganizerProposal) => (
    <div title={proposal.conflict ? proposal.conflict_reason || '重命名冲突' : undefined}>
      {statusForProposal(proposal)}
    </div>
  );

  return (
    <div className="nfc-organizer-preview nfc-organizer-preview-page nfc-v2-organizer-preview nfc-operations-page nfc-page-layout-workbench">
      <PageHeader title={profile.name} description={
        <div className="nfc-plan-header-meta">
          {profile.is_builtin && <span className="nfc-kind-badge">builtin</span>}
          {profile.description && <span>{profile.description}</span>}
        </div>
      } actions={
        <ActionBar compact>
          <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}
            disabled={planLoading} onClick={onBack}>返回方案列表</ConsoleButton>
        </ActionBar>
      } />

      <DataPanel title="整理目标"
        description="Advanced Rules 使用 digest-bound staged Preview：Stage A 结构整理完成后必须 fresh Preview，才会进入 Stage B。"
        className="nfc-complex-form-panel nfc-v2-organizer-target">
        <div className="nfc-v2-organizer-preview-controls">
          <div className="nfc-v2-organizer-root-control">
            <span className="nfc-v2-organizer-root-caption" id="nfc-v2-organizer-root-caption">
              整理目标根目录
            </span>
            <DirectoryPicker multiple={false} value={currentRoot}
              disabled={planLoading} placeholder="点击选择整理根目录..."
              onChange={path => { if (typeof path === 'string') handleRootChange(path); }} />
            <span className="nfc-v2-organizer-help">路径必须在 ALLOWED_ROOTS 白名单内；仅 Preview 会扫描，生成 Plan 不会直接执行。</span>
            {rootError && <span role="alert" className="nfc-v2-organizer-root-error">请选择整理根目录</span>}
          </div>
          <ActionBar>
            <ConsoleButton variant="primary" loading={previewLoading}
              disabled={planLoading} leadingIcon={<ConsoleIcon name="file-search" size={17}/>}
              onClick={handlePreviewClick}>执行只读预览</ConsoleButton>
            {hasPreviewed && summary && (
              <ConsoleButton loading={planLoading} disabled={!canGeneratePlan}
                leadingIcon={<ConsoleIcon name="calendar" size={17} />}
                onClick={() => { void handleGeneratePlan(); }}>
                {structuralRequired ? '生成 Stage A 结构 Plan'
                  : advancedEnabled ? '生成 Stage B 重命名 Plan' : '生成整理 Plan'}
                {stageActionCount > 0 ? ` (${stageActionCount} 项待变更)`
                  : profile.mtime_mode === 'ordered' ? ` (${summary.total_directories} 项 mtime 刷新)` : ''}
              </ConsoleButton>
            )}
            {snapshotId && (
              <span className="nfc-panel-count">
                {previewStageLabel} · snapshot {snapshotId.slice(0, 12)}
              </span>
            )}
          </ActionBar>
          {previewLoading && <div role="status" className="nfc-v2-organizer-preview-loading">
            <span className="nfc-console-spinner" aria-hidden="true" />
            正在执行只读预览…
          </div>}
        </div>
      </DataPanel>

      {summary && (
        <>
          {advancedEnabled && structuralRequired && (
            <div className="nfc-v2-organizer-stage-notice is-warning nfc-organizer-stage-alert" role="alert">
              <ConsoleIcon name="info" size={19} />
              <div><strong>Stage A Structural Preview：Stage B 已锁定</strong>
                <p>当前树包含可折叠的 single-child wrapper。这里只能生成 Stage A MOVE → rmdir_empty 结构计划；执行完成后当前 Preview 立即作废，必须重新 Preview 后才能生成 Stage B。</p>
              </div>
            </div>
          )}
          {advancedEnabled && !structuralRequired && (
            <div className="nfc-v2-organizer-stage-notice is-success nfc-organizer-stage-alert" role="status">
              <ConsoleIcon name="check-circle" size={19} />
              <div><strong>Stage B Rename Preview 已就绪</strong>
                <p>当前 fresh Preview 不再需要结构变更，可基于此 preview digest 生成目录/文件/prefix 重命名计划。</p>
              </div>
            </div>
          )}
          {advancedEnabled && previewDigest && (
            <div className="nfc-organizer-preview-digest">
              <span className="nfc-panel-count">preview digest</span>
              <code>{previewDigest}</code>
            </div>
          )}
          <div className="nfc-metric-grid nfc-organizer-metric-grid">
            <MetricCard label="检测目录" value={summary.total_directories.toLocaleString()} meta="当前 snapshot" />
            <MetricCard label={structuralRequired ? 'Stage A 候选' : '待变更'}
              value={stageActionCount.toLocaleString()}
              meta={structuralRequired ? '仅结构阶段可生成' : 'Stage B / 标准操作'} tone="attention" />
            <MetricCard label="命名冲突" value={summary.conflicts.toLocaleString()}
              meta={summary.conflicts > 0 ? 'Plan 已锁定' : '无阻塞冲突'}
              tone={summary.conflicts > 0 ? 'danger' : 'success'} />
            <MetricCard label="扫描容量" value={formatBytes(summary.total_bytes)} meta="只读统计" />
          </div>
          {summary.conflicts > 0 && (
            <div className="nfc-v2-organizer-stage-notice is-danger nfc-page-alert" role="alert">
              <ConsoleIcon name="info" size={19}/>
              <div><strong>检测到 {summary.conflicts} 个目标命名冲突</strong>
                <p>Preview 返回了 blocking conflict。目标碰撞、时间戳并列、wrapper 形状/目标异常等冲突都会 fail-closed 禁止生成 Plan。</p>
              </div>
            </div>
          )}
          <DataPanel title={structuralRequired ? 'Stage A / Stage B 分段提议' : '整理提议'}
            description={structuralRequired
              ? 'Wrapper collapse 标记为 Stage A；其余 rename/file/prefix 提议属于 Stage B，仅供参考并被锁定，必须在 Stage A 完成后重新 Preview。'
              : '同一 snapshot 下切换过滤和分页，保持 digest 与预览口径一致。'}
            action={<span className="nfc-panel-count">{totalItems} proposals</span>}
            className="nfc-panel-flush nfc-v2-organizer-proposals" variant="dense">
            <ActionBar className="nfc-filter-bar nfc-organizer-preview-filter">
              <div className="nfc-v2-organizer-filter" role="group" aria-label="提议筛选">
                {([
                  ['all', `全部 (${summary.total_directories})`],
                  ['changed', `待变更 (${actionableChanges})`],
                  ['conflicts', `冲突 (${summary.conflicts})`],
                ] as const).map(([key, label]) => (
                  <label key={key} className={filterMode === key ? 'is-selected' : ''}>
                    <input type="radio" name="organizer-proposal-filter" value={key}
                      checked={filterMode === key} disabled={busy}
                      onChange={() => handleFilterChange(key)} />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </ActionBar>
            {proposals.length === 0 ? (
              <ConsoleEmpty title="当前筛选下无整理提议" description="可以切换筛选条件或重新执行只读 Preview。" />
            ) : (
              <ResponsiveDataView
                desktop={
                  <div className="nfc-v2-organizer-proposal-table-scroll" aria-busy={previewLoading}>
                    <table className="nfc-v2-organizer-proposal-table">
                      <caption className="nfc-v2-organizer-sr-only">Organizer 的只读整理提议与冲突</caption>
                      <thead><tr>
                        <th scope="col">阶段 / 规则</th><th scope="col">原路径</th>
                        <th scope="col">预计目标</th><th scope="col">统计</th><th scope="col">状态</th>
                      </tr></thead>
                      <tbody>{proposals.map((proposal, index) => (
                        <tr key={proposal.source + ':' + index}>
                          <td>{stageBadges(proposal)}</td>
                          <td><CodePath value={proposal.source} /></td>
                          <td><div className="nfc-target-path nfc-v2-organizer-target-path">
                            {proposal.changed && <ConsoleIcon name="arrow-right" size={15}/>}
                            <CodePath value={proposal.target} muted={!proposal.changed} />
                          </div></td>
                          <td>{statsBadges(proposal)}</td>
                          <td>{proposalStatus(proposal)}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                }
                mobile={
                  <div className="nfc-mobile-record-list nfc-v2-organizer-proposal-mobile-list" aria-busy={previewLoading}>
                    {proposals.map((proposal, index) => (
                      <article className="nfc-organizer-proposal-mobile-card" key={proposal.source + ':' + index}>
                        <div className="nfc-mobile-record-heading">
                          <div className="nfc-plan-mobile-heading-copy">
                            {stageBadges(proposal)}
                            {statsBadges(proposal)}
                          </div>
                          {proposalStatus(proposal)}
                        </div>
                        <div className="nfc-plan-item-paths">
                          <div className="nfc-plan-item-path-row"><span>源目录</span><CodePath value={proposal.source}/></div>
                          <div className="nfc-plan-item-path-row"><span>目标</span>
                            <CodePath value={proposal.target} muted={!proposal.changed}/></div>
                        </div>
                        {proposal.conflict && <p className="nfc-mobile-record-error">{proposal.conflict_reason || '重命名冲突'}</p>}
                      </article>
                    ))}
                  </div>
                }
              />
            )}
            <ConsolePagination page={page} pageSize={pageSize} total={totalItems}
              pageSizes={[20, 50, 100]} onChange={handlePageChange} />
          </DataPanel>
        </>
      )}
    </div>
  );
};
