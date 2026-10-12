import React, { useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { OperationJournalDrawer } from './OperationJournalDrawer';
import { StaleRebuildDrawer } from '../../components/plans/StaleRebuildDrawer';
import { isWorkflowPlanMetadata, WorkflowPlanMetadata } from '../../types/workflow';
import { plansApi, settingsApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import type { PlanItem } from '../../types';
import { PlanDeleteButton } from '../../components/plans/PlanDeleteButton';
import { invalidatePlanDeleteFailure, getPlanDetailRenderState, getPlanDetailView } from '../../components/plans/plan_cleanup';
import { canPlanLifecycleAction, planConfirmationSnapshot, samePlanConfirmation, type PlanConfirmationSnapshot } from '../../utils/planDetailActions';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const lifecycleSteps = [
  { key: 'draft', label: 'Draft', caption: '预览草稿' },
  { key: 'frozen', label: 'Frozen', caption: '参数冻结' },
  { key: 'validate', label: 'Validate', caption: '实时校验' },
  { key: 'execute', label: 'Execute', caption: '任务执行' },
];

const getLifecycleIndex = (status: string) => {
  if (status === 'draft') return 0;
  if (status === 'frozen' || status === 'validating') return 1;
  if (status === 'ready' || status === 'stale') return 2;
  if (['executing', 'completed', 'partial', 'failed'].includes(status)) return 3;
  return 0;
};

export const PlanDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const planId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const actionInFlight = useRef(false);
  const [confirmation, setConfirmation] = useState<PlanConfirmationSnapshot | null>(null);
  useTitle(`计划详情 #${planId}`);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [journalDrawerOpen, setJournalDrawerOpen] = useState(false);
  const [rebuildDrawerOpen, setRebuildDrawerOpen] = useState(false);

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
  });

  const {
    data: plan,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['planDetail', planId, page, pageSize],
    queryFn: () => plansApi.getPlanDetail(planId, page, pageSize),
    enabled: Number.isSafeInteger(planId) && planId > 0,
  });

  const {
    data: journalData,
    isLoading: isJournalLoading,
    isError: isJournalError,
    refetch: refetchJournal,
  } = useQuery({
    queryKey: ['planOperationJournalSummary', planId],
    queryFn: () => plansApi.getOperationJournal(planId, 1, 1),
    enabled: Number.isSafeInteger(planId) && planId > 0,
  });

  const undoPlanMutation = useMutation({
    mutationFn: () => plansApi.createUndoPlan(planId),
    onSuccess: (res) => {
      toast.success(`已成功创建撤销计划 #${res.id}（共 ${res.total_items} 项逆向操作）`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      toast.error(err.message || '生成撤销计划失败');
    },
  });

  const freezeMutation = useMutation({
    mutationFn: () => plansApi.freezePlan(planId),
    onSuccess: () => {
      toast.success('计划已成功冻结，参数已不可篡改');
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
    },
    onError: (err: any) => {
      toast.error(err.message || '冻结失败');
    },
  });

  const validateMutation = useMutation({
    mutationFn: () => plansApi.validatePlan(planId),
    onSuccess: () => {
      toast.success('计划校验完成，状态已就绪 (Ready)');
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
    },
    onError: (err: any) => {
      toast.error(err.message || '校验失败');
    },
  });

  const executeMutation = useMutation({
    mutationFn: () => plansApi.executePlan(planId),
    onSuccess: (data) => {
      toast.success(`计划已加入任务队列，任务 #${data.work_job_id}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      queryClient.invalidateQueries({ queryKey: ['workJobs'] });
    },
    onError: (err: any) => {
      toast.error(err.message || '执行失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => plansApi.deletePlan(planId),
    onSuccess: () => {
      toast.success(`计划 #${planId} 已安全删除`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      navigate('/plans');
    },
    onError: (err: any) => {
      toast.error(err.message || '删除计划失败');
      invalidatePlanDeleteFailure(queryClient, planId);
    },
  });

  const renderState = getPlanDetailRenderState({
    isLoading,
    isError,
    error,
    hasPlan: !!plan,
  });
  const view = getPlanDetailView(renderState, !!plan);

  if (view === 'loading') {
    return <div className="nfc-centered-state nfc-v2-plan-load" role="status">
      <span className="nfc-console-spinner" aria-hidden="true" />正在载入计划…
    </div>;
  }
  if (view === 'not-found' || view === 'error' || !plan) {
    const missing = view === 'not-found' || !plan && view !== 'error';
    return <div className="nfc-v2-plan-message is-error" role="alert">
      <ConsoleIcon name="info" size={20} />
      <div><strong>{missing ? '计划不存在' : '加载计划失败'}</strong>
        <p>{missing ? '未找到 ID 为 #' + planId + ' 的批处理计划' :
          error instanceof Error ? error.message : '获取计划详情失败，请检查网络或稍后重试'}</p>
      </div>
      <ConsoleButton onClick={() => {
        if (missing) navigate('/plans'); else void refetch();
      }}>{missing ? '返回计划列表' : '重试'}</ConsoleButton>
    </div>;
  }

  const isSafeMode = !settings?.allow_mutation;
  const hasActiveJob = Boolean(plan.active_work_job_id);

  const journalTotal = !isJournalLoading && !isJournalError ? (journalData?.total ?? 0) : 0;
  const isWorkflowPlan = Boolean(isWorkflowPlanMetadata(plan.metadata));
  const workflowMeta = isWorkflowPlan ? (plan.metadata as WorkflowPlanMetadata) : null;
  const isDedupeWorkflowPlan = Boolean(
    workflowMeta && workflowMeta.workflow_mode === 'dedupe'
  );
  const planStorageAction =
    plan.kind === 'dedupe' && typeof plan.metadata?.storage_action === 'string'
      ? plan.metadata.storage_action
      : 'quarantine';
  const isStaleWorkflowPlan = Boolean(
    plan.status === 'stale' && isWorkflowPlan && !isDedupeWorkflowPlan
  );
  const isStaleDedupePlan = Boolean(
    plan.status === 'stale' && (isDedupeWorkflowPlan || plan.kind === 'dedupe')
  );

  const lifecycleIndex = getLifecycleIndex(plan.status);

  const pendingAction = freezeMutation.isPending || validateMutation.isPending ||
    executeMutation.isPending || undoPlanMutation.isPending || deleteMutation.isPending;
  const actionContext = {
    plan, allowMutation: !isSafeMode, journalTotal,
    journalReady: !isJournalLoading && !isJournalError,
    pending: pendingAction || actionInFlight.current,
  };
  const canFreeze = canPlanLifecycleAction('freeze', actionContext);
  const canValidate = canPlanLifecycleAction('validate', actionContext);
  const canExecute = canPlanLifecycleAction('execute', actionContext);
  const canUndo = canPlanLifecycleAction('undo', actionContext);
  const currentConfirmation = confirmation
    ? planConfirmationSnapshot(confirmation.action, actionContext) : null;
  const confirmationValid = samePlanConfirmation(confirmation, currentConfirmation);
  const beginAction = (action: 'freeze' | 'validate') => {
    if (actionInFlight.current || !canPlanLifecycleAction(action, actionContext)) return;
    actionInFlight.current = true;
    const mutation = action === 'freeze' ? freezeMutation : validateMutation;
    mutation.mutate(undefined, { onSettled: () => { actionInFlight.current = false; } });
  };
  const openConfirmation = (action: 'execute' | 'undo') => {
    if (!actionInFlight.current) setConfirmation(planConfirmationSnapshot(action, actionContext));
  };
  const submitConfirmation = async () => {
    if (!confirmation || actionInFlight.current || !confirmationValid ||
        !canPlanLifecycleAction(confirmation.action, actionContext)) {
      setConfirmation(null);
      return;
    }
    const action = confirmation.action;
    actionInFlight.current = true;
    try {
      if (action === 'execute') {
        await executeMutation.mutateAsync();
      } else {
        await undoPlanMutation.mutateAsync();
      }
    } catch {
      // Existing mutation onError reports the server's error.
    } finally {
      actionInFlight.current = false;
      setConfirmation(null);
    }
  };
  const renderTarget = (item: PlanItem) => {
    if (item.target) return <div className="nfc-target-path">
      <ConsoleIcon name="arrow-right" size={16} /><CodePath value={item.target} />
    </div>;
    if (item.keep) return <div className="nfc-target-path">
      <span className="nfc-kind-badge">keep</span><CodePath value={item.keep} />
    </div>;
    return <span className="nfc-table-muted">—</span>;
  };
  const notice = (
    title: string, description: React.ReactNode,
    tone: 'info' | 'warning' | 'error' = 'info', action?: React.ReactNode,
  ) => <div className={'nfc-v2-plan-notice is-' + tone}
    role={tone === 'error' || tone === 'warning' ? 'alert' : 'note'}>
    <ConsoleIcon name={tone === 'warning' ? 'shield-check' : 'info'} size={20} />
    <div className="nfc-v2-plan-notice-body"><strong>{title}</strong>
      <div className="nfc-v2-plan-notice-description">{description}</div></div>
    {action && <div className="nfc-v2-plan-notice-actions">{action}</div>}
  </div>;

  const summaryItems = [
    { label: '计划 ID', value: <span className="nfc-mono">#{plan.id}</span> },
    {
      label: '计划类型',
      value: (
        <div className="nfc-inline-badges">
          <span className="nfc-kind-badge">
            {plan.kind === 'undo' ? 'undo · 撤销计划' : plan.kind}
          </span>
          {(plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id) && (
            <span className="nfc-kind-badge">
              源计划 #{plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id}
            </span>
          )}
        </div>
      ),
    },
    { label: '创建时间', value: formatDateTime(plan.created_at) },
    { label: '预计变更项数', value: `${plan.expected_changes.toLocaleString()} 项`, emphasis: true },
    {
      label: '预计可释放容量',
      value: formatBytes(plan.expected_reclaim_bytes),
      emphasis: true,
    },
    {
      label: '冻结时间',
      value: plan.frozen_at ? formatDateTime(plan.frozen_at) : '未冻结',
    },
  ];

  const mobileItems = (
    <div className="nfc-mobile-record-list">
      {(plan.items || []).length === 0 ? (
        <ConsoleEmpty title="暂无计划项" description="当前计划没有可展示的操作项。" />
      ) : (
        (plan.items || []).map((item: PlanItem) => (
          <article className="nfc-plan-item-mobile-card" key={item.id || `${item.source}_${item.sequence}`}>
            <div className="nfc-mobile-record-heading">
              <div>
                <span className="nfc-mobile-record-title nfc-mono">#{item.sequence}</span>
                <span className={`nfc-operation-badge nfc-operation-${item.operation}`}>
                  {item.operation}
                </span>
              </div>
              <StatusBadge status={item.state} />
            </div>

            <div className="nfc-plan-item-paths">
              <div className="nfc-plan-item-path-row">
                <span>源路径</span>
                <CodePath value={item.source} />
              </div>
              {(item.target || item.keep) && (
                <div className="nfc-plan-item-path-row">
                  <span>{item.target ? '目标路径' : '保留副本'}</span>
                  <CodePath value={item.target || item.keep} />
                </div>
              )}
            </div>

            <div className="nfc-plan-item-meta">
              <span>
                预估容量
                <b>{item.expected_size > 0 ? formatBytes(item.expected_size) : '—'}</b>
              </span>
              <span>
                执行备注
                <b>{item.reason || '—'}</b>
              </span>
            </div>
          </article>
        ))
      )}
    </div>
  );

  return (
    <div className="nfc-operations-page nfc-plan-detail-page nfc-page-layout-detail">
      <PageHeader title={plan.name}
        description={<div className="nfc-plan-header-meta">
          <span className="nfc-mono">Plan #{plan.id}</span>
          <span className="nfc-kind-badge">{plan.kind}</span>
          <StatusBadge status={plan.status} />
        </div>}
        actions={<ActionBar compact>
          <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}
            onClick={() => navigate('/plans')}>返回列表</ConsoleButton>
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void refetch(); }} loading={isFetching}>刷新</ConsoleButton>
        </ActionBar>}
      />
      {planStorageAction === 'hardlink' &&
        notice('Hardlink 计划：两个路径会共享同一个 inode',
          'Hardlink 后两个路径共享同一个 inode，未来通过任一路径写入都会修改同一份文件内容。Freeze / Validate / Worker Execute 仍会重新验证 SHA-256、身份与运行时能力。',
          'warning')}
      {planStorageAction === 'reflink' &&
        notice('Reflink 计划：独立 inode / Copy-on-Write',
          'Reflink 会创建独立 inode，并使用 Copy-on-Write（写时复制）；它不是普通完整复制。Freeze / Validate / Worker Execute 仍会重新验证 SHA-256、身份与运行时能力。')}

      <div className="nfc-lifecycle-strip" aria-label="计划生命周期">
        {lifecycleSteps.map((step, index) => {
          const stateClass =
            index < lifecycleIndex
              ? 'nfc-lifecycle-step-complete'
              : index === lifecycleIndex
                ? 'nfc-lifecycle-step-active'
                : '';
          return (
            <div className={`nfc-lifecycle-step ${stateClass}`.trim()} key={step.key}>
              <span className="nfc-lifecycle-step-index">{index + 1}</span>
              <span className="nfc-lifecycle-step-copy">
                <strong>{step.label}</strong>
                <span>{step.caption}</span>
              </span>
            </div>
          );
        })}
      </div>

      <section className="nfc-plan-action-surface nfc-v2-plan-actions" aria-label="计划安全操作">
        <ActionBar>
          {plan.status === 'draft' && (
            <ConsoleButton leadingIcon={<ConsoleIcon name="lock" size={16} />}
              onClick={() => beginAction('freeze')} disabled={!canFreeze}
              loading={freezeMutation.isPending}>
              冻结计划 (Freeze)
            </ConsoleButton>
          )}
          {['frozen', 'ready', 'partial', 'stale'].includes(plan.status) && (
            <span title={hasActiveJob ?
              '该计划当前已有执行任务进行中 (任务 #' + plan.active_work_job_id + ')' : undefined}>
              <ConsoleButton leadingIcon={<ConsoleIcon name="check-circle" size={16} />}
                disabled={!canValidate} loading={validateMutation.isPending}
                onClick={() => beginAction('validate')}>
                SHA256 实时校验 (Validate)
              </ConsoleButton>
            </span>
          )}
          {['ready', 'partial'].includes(plan.status) && (
            <span title={isSafeMode ?
              '当前处于只读安全模式 (ALLOW_MUTATION=false)，执行按钮已锁定。' :
              hasActiveJob ? '当前存在执行任务 #' + plan.active_work_job_id : undefined}>
              <ConsoleButton variant="danger" leadingIcon={<ConsoleIcon name="play" size={16} />}
                disabled={!canExecute} loading={executeMutation.isPending}
                onClick={() => openConfirmation('execute')}>
                执行计划 (Execute)
              </ConsoleButton>
            </span>
          )}
          <ConsoleButton leadingIcon={<ConsoleIcon name="history" size={16} />}
            onClick={() => { void refetchJournal(); setJournalDrawerOpen(true); }}>
            操作日志 {journalTotal > 0 ? '(' + journalTotal + ')' : ''}
          </ConsoleButton>
          {['completed', 'partial'].includes(plan.status) && journalTotal > 0 && (
            <span title={hasActiveJob ?
              '该计划当前已有执行任务进行中 (任务 #' + plan.active_work_job_id + ')' : undefined}>
              <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
                loading={undoPlanMutation.isPending} disabled={!canUndo}
                onClick={() => openConfirmation('undo')}>
                生成撤销计划 (Undo)
              </ConsoleButton>
            </span>
          )}
          {isStaleWorkflowPlan && (
            <ConsoleButton leadingIcon={<ConsoleIcon name="layers" size={16} />}
              onClick={() => setRebuildDrawerOpen(true)}>
              重建工作流计划 (Rebuild Plan)
            </ConsoleButton>
          )}
          {isStaleDedupePlan && workflowMeta && (
            <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}
              onClick={() => navigate('/workflows/' + workflowMeta.workflow_id)}>
              返回关联工作流
            </ConsoleButton>
          )}
          <PlanDeleteButton plan={plan}
            onDelete={() => deleteMutation.mutateAsync()}
            loading={deleteMutation.isPending}
            type="default" size="middle" />
        </ActionBar>
      </section>

      <div className="nfc-plan-alert-stack nfc-v2-plan-alerts">
        {(plan.kind === 'undo' || plan.metadata?.is_undo) &&
          notice(
            '撤销还原计划 (Undo Plan for #' +
              (plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id || 'Unknown') + ')',
            <div>
              本计划为原计划的撤销还原计划。所有操作项已根据底层 Operation Journal 严格倒序排布。
              <div className="nfc-alert-emphasis">
                安全声明：Undo 计划绝不支持直接原地执行，必须严格按照常规生命周期完成 Freeze 冻结与实时 SHA256 校验后方可通过任务中心安全执行。
              </div>
            </div>, 'info',
            (plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id) &&
              <ConsoleButton size="sm"
                onClick={() => navigate('/plans/' +
                  (plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id))}>
                查看原计划
              </ConsoleButton>,
          )}
        {plan.status === 'stale' && notice(
          isStaleDedupePlan
            ? '去重执行计划已过期锁定 (PLAN_STALE)'
            : isStaleWorkflowPlan
              ? '工作流计划已过期 (PLAN_STALE)'
              : '计划已过期 (PLAN_STALE)',
          isStaleDedupePlan ? <div>
            去重候选文件已被外部修改、移动、删除或哈希变动。去重计划涉及数据安全，严禁原地增量重建。
            <div className="nfc-alert-followup">
              处置建议：请重新执行全量扫描，获取最新重复组快照后
              {workflowMeta
                ? '返回关联工作流（#' + workflowMeta.workflow_id + '）重新生成去重计划。'
                : '前往高级去重页面重新生成计划草案。'}
            </div>
          </div> : isStaleWorkflowPlan
            ? '计划中的源文件已被外部修改、移动、删除或替换。计划已锁定。可基于原工作流历史版本与快照参数重新构建全新草稿。'
            : '计划中的源文件已被外部修改、移动、删除或替换。计划已锁定，严禁执行。如需继续操作，请删除此计划并重新生成。',
          'error',
          isStaleDedupePlan
            ? <ActionBar compact>
                {workflowMeta && <ConsoleButton variant="primary" size="sm"
                  onClick={() => navigate('/workflows/' + workflowMeta.workflow_id)}>
                  返回关联工作流
                </ConsoleButton>}
                <ConsoleButton size="sm" onClick={() => navigate('/scans')}>前往扫描任务</ConsoleButton>
              </ActionBar>
            : isStaleWorkflowPlan
              ? <ConsoleButton size="sm" variant="primary"
                  onClick={() => setRebuildDrawerOpen(true)}>重建计划预览</ConsoleButton>
              : undefined,
        )}
        {isSafeMode && notice('只读安全保护模式生效中',
          '系统当前以 ALLOW_MUTATION=false 运行。可安全生成 Dry Run 与 SHA256 校验，但不能直接触发 Execute。')}
      </div>

      <DataPanel
        title="计划摘要"
        description="冻结参数、预期变更与执行前安全上下文。"
        className="nfc-plan-summary nfc-panel-flush"
      >
        <ResponsiveDescriptions items={summaryItems} />
      </DataPanel>

      <DataPanel
        title="计划项清单"
        description="每一项真实文件操作都必须在校验后由既有 Worker 执行链处理。"
        action={
          <span className="nfc-panel-count">
            {plan.total_items ?? plan.expected_changes} items
          </span>
        }
        className="nfc-panel-flush"
        variant="dense"
      >
        <ResponsiveDataView
          desktop={
            <Table
              dataSource={plan.items || []}
              columns={columns}
              rowKey={(record) => record.id || `${record.source}_${record.sequence}`}
              scroll={{ x: 1180 }}
              pagination={{
                current: page,
                pageSize,
                total: plan.total_items ?? plan.expected_changes,
                showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100', '200'],
                onChange: (p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                },
              }}
            />
          }
          mobile={
            <>
              {mobileItems}
              <div className="nfc-mobile-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={plan.total_items ?? plan.expected_changes}
                  showSizeChanger
                  pageSizeOptions={['20', '50', '100', '200']}
                  onChange={(p, ps) => {
                    setPage(p);
                    setPageSize(ps);
                  }}
                />
              </div>
            </>
          }
        />
      </DataPanel>

      <OperationJournalDrawer
        planId={planId}
        open={journalDrawerOpen}
        onClose={() => setJournalDrawerOpen(false)}
      />

      {isStaleWorkflowPlan && (
        <StaleRebuildDrawer
          open={rebuildDrawerOpen}
          planId={planId}
          onClose={() => setRebuildDrawerOpen(false)}
          onRebuildSuccess={(newPlanId) => {
            queryClient.invalidateQueries({ queryKey: ['plansList'] });
            navigate(`/plans/${newPlanId}`);
          }}
        />
      )}
    </div>
  );
};
