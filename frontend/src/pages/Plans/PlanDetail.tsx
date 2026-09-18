import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Empty,
  message,
  Pagination,
  Popconfirm,
  Spin,
  Table,
  Tooltip,
} from 'antd';
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  BuildOutlined,
  CheckCircleOutlined,
  HistoryOutlined,
  LockOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RollbackOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { OperationJournalDrawer } from './OperationJournalDrawer';
import { StaleRebuildDrawer } from '../../components/plans/StaleRebuildDrawer';
import { isWorkflowPlanMetadata, WorkflowPlanMetadata } from '../../types/workflow';
import { plansApi, settingsApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { PlanItem } from '../../types';
import { PlanDeleteButton } from '../../components/plans/PlanDeleteButton';
import {
  invalidatePlanDeleteFailure,
  getPlanDetailRenderState,
  getPlanDetailView,
} from '../../components/plans/plan_cleanup';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';

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
  });

  const {
    data: journalData,
    isLoading: isJournalLoading,
    isError: isJournalError,
    refetch: refetchJournal,
  } = useQuery({
    queryKey: ['planOperationJournalSummary', planId],
    queryFn: () => plansApi.getOperationJournal(planId, 1, 1),
    enabled: !!planId,
  });

  const undoPlanMutation = useMutation({
    mutationFn: () => plansApi.createUndoPlan(planId),
    onSuccess: (res) => {
      message.success(`已成功创建撤销计划 #${res.id}（共 ${res.total_items} 项逆向操作）`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成撤销计划失败');
    },
  });

  const freezeMutation = useMutation({
    mutationFn: () => plansApi.freezePlan(planId),
    onSuccess: () => {
      message.success('计划已成功冻结，参数已不可篡改');
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
    },
    onError: (err: any) => {
      message.error(err.message || '冻结失败');
    },
  });

  const validateMutation = useMutation({
    mutationFn: () => plansApi.validatePlan(planId),
    onSuccess: () => {
      message.success('计划校验完成，状态已就绪 (Ready)');
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
    },
    onError: (err: any) => {
      message.error(err.message || '校验失败');
    },
  });

  const executeMutation = useMutation({
    mutationFn: () => plansApi.executePlan(planId),
    onSuccess: (data) => {
      message.success(`计划已加入任务队列，任务 #${data.work_job_id}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      queryClient.invalidateQueries({ queryKey: ['workJobs'] });
    },
    onError: (err: any) => {
      message.error(err.message || '执行失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => plansApi.deletePlan(planId),
    onSuccess: () => {
      message.success(`计划 #${planId} 已安全删除`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      navigate('/plans');
    },
    onError: (err: any) => {
      message.error(err.message || '删除计划失败');
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
    return (
      <div className="nfc-centered-state">
        <Spin size="large" />
      </div>
    );
  }

  if (view === 'not-found') {
    return (
      <Alert
        message="计划不存在"
        description={`未找到 ID 为 #${planId} 的批处理计划`}
        type="error"
        showIcon
        action={<Button onClick={() => navigate('/plans')}>返回计划列表</Button>}
      />
    );
  }

  if (view === 'error') {
    return (
      <Alert
        message="加载计划失败"
        description={(error as any)?.message || '获取计划详情失败，请检查网络或稍后重试'}
        type="error"
        showIcon
        action={<Button onClick={() => refetch()}>重试</Button>}
      />
    );
  }

  if (!plan) {
    return (
      <Alert
        message="计划不存在"
        description={`未找到 ID 为 #${planId} 的批处理计划`}
        type="error"
        showIcon
        action={<Button onClick={() => navigate('/plans')}>返回计划列表</Button>}
      />
    );
  }

  const isSafeMode = !settings?.allow_mutation;
  const hasActiveJob = Boolean(plan.active_work_job_id);
  const executeDisabled = isSafeMode || hasActiveJob;

  const journalTotal = !isJournalLoading && !isJournalError ? (journalData?.total ?? 0) : 0;
  const canCreateUndo =
    (plan.status === 'completed' || plan.status === 'partial') &&
    journalTotal > 0 &&
    !isJournalLoading &&
    !isJournalError;

  const isWorkflowPlan = Boolean(isWorkflowPlanMetadata(plan.metadata));
  const workflowMeta = isWorkflowPlan ? (plan.metadata as WorkflowPlanMetadata) : null;
  const isDedupeWorkflowPlan = Boolean(
    workflowMeta && workflowMeta.workflow_mode === 'dedupe'
  );
  const isStaleWorkflowPlan = Boolean(
    plan.status === 'stale' && isWorkflowPlan && !isDedupeWorkflowPlan
  );
  const isStaleDedupePlan = Boolean(
    plan.status === 'stale' && (isDedupeWorkflowPlan || plan.kind === 'dedupe')
  );

  const lifecycleIndex = getLifecycleIndex(plan.status);

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 72,
      render: (seq: number) => <span className="nfc-mono">#{seq}</span>,
    },
    {
      title: '操作',
      dataIndex: 'operation',
      key: 'operation',
      width: 112,
      render: (op: string) => (
        <span className={`nfc-operation-badge nfc-operation-${op}`}>{op}</span>
      ),
    },
    {
      title: '源文件 / 待操作路径',
      dataIndex: 'source',
      key: 'source',
      render: (value: string) => <CodePath value={value} />,
    },
    {
      title: '目标路径 / 保留副本',
      key: 'target_or_keep',
      render: (_: unknown, record: PlanItem) => {
        if (record.target) {
          return (
            <div className="nfc-target-path">
              <ArrowRightOutlined />
              <CodePath value={record.target} />
            </div>
          );
        }
        if (record.keep) {
          return (
            <div className="nfc-target-path">
              <span className="nfc-kind-badge">keep</span>
              <CodePath value={record.keep} />
            </div>
          );
        }
        return <span className="nfc-table-muted">—</span>;
      },
    },
    {
      title: '预估容量',
      dataIndex: 'expected_size',
      key: 'expected_size',
      width: 110,
      render: (bytes: number) => (bytes > 0 ? formatBytes(bytes) : '—'),
    },
    {
      title: '校验状态',
      dataIndex: 'state',
      key: 'state',
      width: 122,
      render: (state: string) => <StatusBadge status={state} />,
    },
    {
      title: '执行备注',
      dataIndex: 'reason',
      key: 'reason',
      width: 180,
      render: (reason: string) => reason || <span className="nfc-table-muted">—</span>,
    },
  ];

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
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无计划项" />
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
    <div className="nfc-operations-page nfc-plan-detail-page">
      <PageHeader
        eyebrow="EXECUTION PLAN"
        title={plan.name}
        description={
          <div className="nfc-plan-header-meta">
            <span className="nfc-mono">Plan #{plan.id}</span>
            <span className="nfc-kind-badge">{plan.kind}</span>
            <StatusBadge status={plan.status} />
          </div>
        }
        actions={
          <ActionBar compact>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/plans')}>
              返回列表
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>
              刷新
            </Button>
          </ActionBar>
        }
      />

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

      <section className="nfc-plan-action-surface" aria-label="计划安全操作">
        <ActionBar>
          {plan.status === 'draft' && (
            <Button
              icon={<LockOutlined />}
              onClick={() => freezeMutation.mutate()}
              loading={freezeMutation.isPending}
            >
              冻结计划 (Freeze)
            </Button>
          )}

          {(plan.status === 'frozen' ||
            plan.status === 'ready' ||
            plan.status === 'partial' ||
            plan.status === 'stale') && (
            <Tooltip
              title={
                hasActiveJob
                  ? `该计划当前已有执行任务进行中 (任务 #${plan.active_work_job_id})`
                  : undefined
              }
            >
              <span>
                <Button
                  icon={<CheckCircleOutlined />}
                  onClick={() => validateMutation.mutate()}
                  loading={validateMutation.isPending}
                  disabled={hasActiveJob}
                >
                  SHA256 实时校验 (Validate)
                </Button>
              </span>
            </Tooltip>
          )}

          {(plan.status === 'ready' || plan.status === 'partial') && (
            <Tooltip
              title={
                isSafeMode
                  ? '当前处于只读安全模式 (ALLOW_MUTATION=false)，执行按钮已被锁定。若确认执行，请修改 compose 环境变量开启允许写入。'
                  : hasActiveJob
                    ? `该计划当前已有执行任务进行中 (任务 #${plan.active_work_job_id})`
                    : '执行计划：将按计划安全变更/隔离文件'
              }
            >
              <span>
                <Popconfirm
                  title="确认执行计划？"
                  description="请确认您已仔细核对所有计划项并完成了校验。"
                  onConfirm={() => executeMutation.mutate()}
                  disabled={executeDisabled}
                  okText="确认执行"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button
                    type="primary"
                    danger
                    icon={<PlayCircleOutlined />}
                    disabled={executeDisabled}
                    loading={executeMutation.isPending}
                  >
                    执行计划 (Execute)
                  </Button>
                </Popconfirm>
              </span>
            </Tooltip>
          )}

          <Button
            icon={<HistoryOutlined />}
            onClick={() => {
              refetchJournal();
              setJournalDrawerOpen(true);
            }}
          >
            操作日志 {journalTotal > 0 ? `(${journalTotal})` : ''}
          </Button>

          {canCreateUndo && (
            <Tooltip
              title={
                hasActiveJob
                  ? `该计划当前已有执行任务进行中 (任务 #${plan.active_work_job_id})`
                  : '基于底层操作日志倒序生成一份逆向还原计划'
              }
            >
              <span>
                <Popconfirm
                  title="确认生成撤销计划？"
                  description="系统将基于该计划已完成的操作日志（Operation Journal）倒序生成一份新的 Undo 计划。新计划为独立草稿态，仍需按常规流程完成参数冻结与实时校验后方可执行。"
                  onConfirm={() => undoPlanMutation.mutate()}
                  disabled={hasActiveJob || undoPlanMutation.isPending}
                  okText="生成撤销计划"
                  cancelText="取消"
                >
                  <Button
                    icon={<RollbackOutlined />}
                    loading={undoPlanMutation.isPending}
                    disabled={hasActiveJob}
                  >
                    生成撤销计划 (Undo)
                  </Button>
                </Popconfirm>
              </span>
            </Tooltip>
          )}

          {isStaleWorkflowPlan && (
            <Button
              icon={<BuildOutlined />}
              onClick={() => setRebuildDrawerOpen(true)}
            >
              重建工作流计划 (Rebuild Plan)
            </Button>
          )}

          {isStaleDedupePlan && workflowMeta && (
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(`/workflows/${workflowMeta.workflow_id}`)}
            >
              返回关联工作流
            </Button>
          )}

          <PlanDeleteButton
            plan={plan}
            onDelete={() => deleteMutation.mutate()}
            loading={deleteMutation.isPending}
            type="default"
            size="middle"
          />
        </ActionBar>
      </section>

      <div className="nfc-plan-alert-stack">
        {(plan.kind === 'undo' || plan.metadata?.is_undo) && (
          <Alert
            message={`撤销还原计划 (Undo Plan for #${plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id || 'Unknown'})`}
            description={
              <div>
                本计划为计划 #{plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id} 的撤销还原计划。所有操作项已根据底层操作日志严格倒序排布。
                <div className="nfc-alert-emphasis">
                  安全声明：Undo 计划绝不支持直接原地执行，必须严格按照常规生命周期完成 Freeze 冻结与实时 SHA256 校验后方可通过任务中心安全执行。
                </div>
              </div>
            }
            type="info"
            showIcon
            icon={<RollbackOutlined />}
            action={
              plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id ? (
                <Button
                  size="small"
                  onClick={() =>
                    navigate(
                      `/plans/${plan.metadata?.undo_of_plan_id || plan.metadata?.undo_for_plan_id}`
                    )
                  }
                >
                  查看原计划
                </Button>
              ) : undefined
            }
          />
        )}

        {plan.status === 'stale' && (
          <Alert
            message={
              isStaleDedupePlan
                ? '去重执行计划已过期锁定 (PLAN_STALE)'
                : isStaleWorkflowPlan
                  ? '工作流计划已过期 (PLAN_STALE)'
                  : '计划已过期 (PLAN_STALE)'
            }
            description={
              isStaleDedupePlan ? (
                <div>
                  去重候选文件已被外部修改、移动、删除或哈希变动。去重计划涉及数据安全，严禁原地增量重建。
                  <div className="nfc-alert-followup">
                    处置建议：请先重新执行全量扫描任务以获取最新重复组快照，然后
                    {workflowMeta ? (
                      <span>返回关联工作流（#{workflowMeta.workflow_id}）重新生成去重计划。</span>
                    ) : (
                      <span>前往高级去重页面重新生成计划草案。</span>
                    )}
                  </div>
                </div>
              ) : isStaleWorkflowPlan ? (
                '计划中的源文件已被外部修改、移动、删除或替换。为保障 NAS 数据安全，该计划已被锁定。由于此计划源自工作流，您可以基于原始工作流历史版本与快照参数重新构建全新草稿。'
              ) : (
                '计划中的源文件已被外部修改、移动、删除或替换。为保障 NAS 数据安全，该计划已被锁定，严禁执行。如需继续操作，请删除此计划并重新生成。'
              )
            }
            type="error"
            showIcon
            action={
              isStaleDedupePlan ? (
                <ActionBar compact>
                  {workflowMeta && (
                    <Button
                      type="primary"
                      onClick={() => navigate(`/workflows/${workflowMeta.workflow_id}`)}
                    >
                      返回关联工作流
                    </Button>
                  )}
                  <Button onClick={() => navigate('/scans')}>前往扫描任务</Button>
                </ActionBar>
              ) : isStaleWorkflowPlan ? (
                <Button type="primary" onClick={() => setRebuildDrawerOpen(true)}>
                  重建计划预览
                </Button>
              ) : undefined
            }
          />
        )}

        {isSafeMode && (
          <Alert
            message="只读安全保护模式生效中"
            description="系统当前以 ALLOW_MUTATION=false 运行。您可以安全进行 Dry Run 计划生成与 SHA256 校验，但无法直接触发 Execute 执行。"
            type="info"
            showIcon
            icon={<LockOutlined />}
          />
        )}
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
