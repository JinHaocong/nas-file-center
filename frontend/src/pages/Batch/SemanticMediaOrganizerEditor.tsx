import React, { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { DataPanel } from '../../components/ui/DataPanel';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { tasksApi } from '../../api/tasks';
import { getStructuredApiError } from '../../api/errors';
import {
  mediaOrganizerApi, executableSemanticUnits, semanticExecutionNeedsPolling,
  canConfirmSemanticCleanup, canRecoverSemanticCleanup,
  semanticExecutionIdFromSearch, withSemanticExecutionId,
  type SemanticUnitPreview, type SemanticCleanupLink, type SemanticCleanupPlan,
} from '../../api/media_organizer';

const isRunning = (status: string | undefined) =>
  status === 'queued' || status === 'running' ||
  status === 'cancel_requested' || status === 'paused';

const unitStatus = (item: SemanticUnitPreview): [string, string] => {
  if (item.status === 'blocked') return ['failed', '需要人工检查'];
  if (item.status === 'ready') return ['ready', '待整理'];
  if (item.status === 'already_organized') return ['completed', '已整理'];
  return ['skipped', '无需处理'];
};

const kindDescription = (item: SemanticUnitPreview) => {
  if (item.operation === 'flatten_pure_media') return '单种媒体不超过 200 个：平铺后从 001 统一编号';
  if (item.operation === 'bucket_pure_media') return '单种媒体超过 200 个：每组最多 200';
  if (item.operation === 'sort_mixed_media') return '图片、视频、其他文件分组整理';
  return item.reason || '当前目录无待处理文件';
};

const CleanupLinks: React.FC<{
  title: string;
  links: (SemanticCleanupLink & { stage_path?: string })[];
  pathLabel?: string;
  showStage?: boolean;
}> = ({ title, links, pathLabel = '待清理路径', showStage = false }) => (
  <div className="nfc-v2-batch-media-scroll">
    <table className="nfc-v2-batch-media-table">
      <caption>{title}</caption>
      <thead><tr><th scope="col">{pathLabel}</th><th scope="col">最终文件路径</th>
        {showStage && <th scope="col">已核验暂存路径</th>}</tr></thead>
      <tbody>
        {links.map(link => (
          <tr key={link.path}>
            <td><CodePath value={link.path} /></td>
            <td><CodePath value={link.published_path} /></td>
            {showStage && <td><CodePath value={link.stage_path || ''} /></td>}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export const SemanticCleanupPlanInventory: React.FC<{
  plan: SemanticCleanupPlan;
  page: number;
  pageSize: number;
  busy: boolean;
  onPageChange: (page: number, pageSize: number) => void;
}> = ({ plan, page, pageSize, busy, onPageChange }) => (
  <>
    {plan.verification_scope === 'worker_handoff_snapshot' && (
      <p className="nfc-form-note" role="status">
        这份冻结清单记录上次 Worker 完整核验的结果。Worker 会在执行前再次核验所有文件和目录，
        发现变化即停止执行。
      </p>
    )}
    <div className="nfc-v2-batch-media-stats" role="status">
      <span>清理原始路径 <strong>{plan.total_original_links.toLocaleString()}</strong></span>
      <span>清理暂存路径 <strong>{plan.total_staged_links.toLocaleString()}</strong></span>
      <span>确认后释放路径 <strong>{plan.total_released_original_links.toLocaleString()}</strong></span>
      <span>确认后完成发布 <strong>{plan.total_deferred_publications.toLocaleString()}</strong></span>
      <span>保留文件 <strong>{plan.total_retained_original_links.toLocaleString()}</strong></span>
      <span>清理旧目录 <strong>{plan.wrapper_directories.length.toLocaleString()}</strong></span>
      <span>保留目标目录 <strong>{plan.retained_wrapper_directories.length.toLocaleString()}</strong></span>
    </div>
    <p className="nfc-form-note">以上数量属于冻结清单，不代表清理开始后的当前剩余进度。</p>
    <CleanupLinks title="确认后释放的原始路径" links={plan.released_original_links}
      pathLabel="确认后释放路径" showStage />
    <CleanupLinks title="确认后完成发布的目标"
      pathLabel="原始来源路径" showStage links={plan.deferred_publications.map(row => ({
        path: row.source_path, published_path: row.path,
        stage_path: row.stage_path, identity: row.identity,
      }))} />
    <CleanupLinks title="保留的最终文件" links={plan.retained_original_links} pathLabel="保留路径" />
    <CleanupLinks title="原始路径清理清单" links={plan.original_links} />
    <CleanupLinks title="暂存路径清理清单" links={plan.staged_links} />
    <ConsolePagination page={page} pageSize={pageSize}
      total={Math.max(plan.total_original_links, plan.total_staged_links,
        plan.total_deferred_publications, plan.total_released_original_links,
        plan.total_retained_original_links)}
      pageSizes={[25, 50, 100]}
      onChange={(next, size) => { if (!busy) onPageChange(next, size); }} />
    <div className="nfc-v2-batch-field">
      <span>保留的目标目录</span>
      {plan.retained_wrapper_directories.length ? (
        <ul>{plan.retained_wrapper_directories.map(folder => (
          <li key={folder.path}><CodePath value={folder.path} /></li>
        ))}</ul>
      ) : <small>没有需要沿用的原始目标目录。</small>}
      <span>待清理的旧分类目录</span>
      {plan.wrapper_directories.length ? (
        <ul>{plan.wrapper_directories.map(folder => (
          <li key={folder.path}><CodePath value={folder.path} /></li>
        ))}</ul>
      ) : <small>没有需要移除的旧分类目录。</small>}
      <span>暂存目录：<CodePath value={plan.stage.path} /></span>
    </div>
  </>
);

/** Preview-first workflow. Execution is default-off and requires explicit unit approval. */
export const SemanticMediaOrganizerEditor: React.FC = () => {
  const toast = useConsoleToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const executionJobId = semanticExecutionIdFromSearch(searchParams);
  const invalidExecutionId = searchParams.has('execution') && executionJobId === null;
  const setExecutionJobId = (id: number | null) => {
    setSearchParams(current => withSemanticExecutionId(current, id), { replace: true });
  };
  const [selection, setSelection] = useState('');
  const [jobId, setJobId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedUnit, setSelectedUnit] = useState('');
  const [executionConfirmation, setExecutionConfirmation] = useState('');
  const [recoveryConfirmation, setRecoveryConfirmation] = useState('');
  const [cleanupReviewOpen, setCleanupReviewOpen] = useState(false);
  const [cleanupPage, setCleanupPage] = useState(1);
  const [cleanupPageSize, setCleanupPageSize] = useState(25);
  const [cleanupConfirmation, setCleanupConfirmation] = useState('');
  const [cleanupRecoveryConfirmation, setCleanupRecoveryConfirmation] = useState('');
  const [expectedCleanupJobId, setExpectedCleanupJobId] = useState<number | null>(null);
  const [mappingSelection, setMappingSelection] = useState<{ unit: string; mappingId: string } | null>(null);
  const [mappingPage, setMappingPage] = useState(1);
  const [mappingPageSize, setMappingPageSize] = useState(50);
  const enqueue = useMutation({ mutationFn: mediaOrganizerApi.startPreview });
  const startExecution = useMutation({
    mutationFn: ({ previewId, unit, confirmation }: {
      previewId: number; unit: string; confirmation: string;
    }) => mediaOrganizerApi.startExecution(previewId, unit, confirmation),
  });
  const recoverExecution = useMutation({
    mutationFn: ({ executionId, confirmation }: {
      executionId: number; confirmation: string;
    }) => mediaOrganizerApi.recoverExecution(executionId, confirmation),
  });
  const startCleanup = useMutation({
    mutationFn: ({ executionId, confirmation }: { executionId: number; confirmation: string }) =>
      mediaOrganizerApi.startCleanup(executionId, confirmation),
  });
  const recoverCleanup = useMutation({
    mutationFn: ({ cleanupId, confirmation }: { cleanupId: number; confirmation: string }) =>
      mediaOrganizerApi.recoverCleanup(cleanupId, confirmation),
  });
  const cancel = useMutation({ mutationFn: tasksApi.cancelTask });
  const { data, isError, error, isFetching } = useQuery({
    queryKey: ['semanticMediaPreview', jobId, page, pageSize, statusFilter],
    queryFn: () => mediaOrganizerApi.getPreview(jobId!, page, pageSize, statusFilter),
    enabled: jobId !== null,
    refetchInterval: query => isRunning(query.state.data?.status) ? 1500 : false,
  });
  const { data: mappingData, isError: mappingLoadFailed,
    error: mappingLoadError, isFetching: mappingFetching } = useQuery({
    queryKey: ['semanticMediaMapping', jobId, mappingSelection?.mappingId, mappingPage, mappingPageSize],
    queryFn: () => mediaOrganizerApi.getMapping(
      jobId!, mappingSelection!.mappingId, mappingPage, mappingPageSize,
    ),
    enabled: jobId !== null && mappingSelection !== null && data?.status === 'completed',
  });
  const { data: executionStatus, isError: executionLoadFailed,
    error: executionLoadError, refetch: refetchExecution } = useQuery({
    queryKey: ['semanticMediaExecution', executionJobId],
    queryFn: () => mediaOrganizerApi.getExecution(executionJobId!),
    enabled: executionJobId !== null,
    retry: false,
    refetchInterval: query => query.state.status === 'error' && !query.state.data ? false :
      semanticExecutionNeedsPolling(query.state.data, expectedCleanupJobId) ? 1500 : false,
  });
  useEffect(() => {
    setCleanupReviewOpen(false);
    setCleanupPage(1);
    setCleanupConfirmation('');
    setCleanupRecoveryConfirmation('');
    setRecoveryConfirmation('');
    setExpectedCleanupJobId(null);
  }, [executionJobId]);
  useEffect(() => {
    if (jobId === null && executionStatus?.job_id === executionJobId) {
      setSelection(executionStatus.unit);
    }
  }, [executionJobId, executionStatus?.job_id, executionStatus?.unit, jobId]);
  useEffect(() => {
    if (expectedCleanupJobId !== null && executionStatus?.cleanup?.job_id === expectedCleanupJobId) {
      setExpectedCleanupJobId(null);
    }
  }, [expectedCleanupJobId, executionStatus?.cleanup?.job_id]);
  const cleanupReviewAvailable = executionStatus?.status === 'completed' &&
    executionStatus.manual_cleanup_required && !executionStatus.finalized && !executionStatus.cleanup;
  const { data: cleanupPlan, isError: cleanupPlanFailed, error: cleanupPlanError,
    isFetching: cleanupPlanFetching, refetch: refetchCleanupPlan } = useQuery({
    queryKey: ['semanticMediaCleanupPlan', executionJobId, cleanupPage, cleanupPageSize],
    queryFn: () => mediaOrganizerApi.getCleanupPlan(executionJobId!, cleanupPage, cleanupPageSize),
    enabled: executionJobId !== null && cleanupReviewOpen && cleanupReviewAvailable,
    retry: false,
  });
  const busy = enqueue.isPending || startExecution.isPending || recoverExecution.isPending ||
    startCleanup.isPending || recoverCleanup.isPending || isRunning(data?.status) ||
    (executionJobId !== null && (executionStatus
      ? semanticExecutionNeedsPolling(executionStatus, expectedCleanupJobId) : !executionLoadFailed)) ||
    (jobId !== null && data == null);
  const summary = data?.summary;
  const executableUnits = executableSemanticUnits(data);
  const readyUnit = executableUnits.find(row => row.unit === selectedUnit);
  const expectedConfirmation = data?.confirmation_tokens?.[selectedUnit] || '';
  const canExecute = Boolean(data?.execution_enabled && data?.status === 'completed' &&
    summary && summary.blocked_count === 0 && readyUnit && expectedConfirmation &&
    executionConfirmation === expectedConfirmation && !busy &&
    !startExecution.isPending && executionJobId === null);
  const recoveryToken = executionJobId === null ? '' :
    `RECOVER_MEDIA_ORGANIZER_EXECUTION_${executionJobId}`;
  const canRecover = Boolean(executionStatus?.execution_enabled && executionJobId !== null &&
    executionStatus?.status === 'failed' &&
    executionStatus.recovery_of_job_id == null &&
    recoveryConfirmation === recoveryToken && !busy && !recoverExecution.isPending);
  const canCleanup = Boolean(!busy && !cleanupPlanFetching &&
    canConfirmSemanticCleanup(executionStatus, cleanupPlan, cleanupConfirmation));
  const canRecoverCleanup = Boolean(!busy &&
    canRecoverSemanticCleanup(executionStatus, cleanupRecoveryConfirmation));

  const resetCleanup = () => {
    setCleanupReviewOpen(false);
    setCleanupPage(1);
    setCleanupConfirmation('');
    setCleanupRecoveryConfirmation('');
    setExpectedCleanupJobId(null);
  };

  const changeSelection = (next: string | string[]) => {
    if (busy) return;
    setSelection(Array.isArray(next) ? next[0] || '' : next);
    setJobId(null);
    setSelectedUnit('');
    setExecutionConfirmation('');
    setExecutionJobId(null);
    setRecoveryConfirmation('');
    resetCleanup();
    setMappingSelection(null);
    setMappingPage(1);
    setPage(1);
    setStatusFilter('all');
  };

  const start = async () => {
    const chosen = selection.trim();
    if (!chosen.startsWith('/')) {
      toast.error('请选择允许访问范围内的绝对目录');
      return;
    }
    if (busy) return;
    setJobId(null);
    setSelectedUnit('');
    setExecutionConfirmation('');
    setExecutionJobId(null);
    setRecoveryConfirmation('');
    resetCleanup();
    setMappingSelection(null);
    setMappingPage(1);
    setPage(1);
    setStatusFilter('all');
    try {
      const response = await enqueue.mutateAsync(chosen);
      setJobId(response.job_id);
      toast.success(`只读扫描任务 #${response.job_id} 已加入 Worker 队列`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '无法开始只读扫描');
    }
  };

  const stop = async () => {
    if (jobId === null || !isRunning(data?.status) || cancel.isPending) return;
    try {
      await cancel.mutateAsync(jobId);
      toast.success('已请求取消只读扫描');
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '取消扫描失败');
    }
  };

  const executeCurrentUnit = async () => {
    if (!canExecute || jobId === null) return;
    try {
      const response = await startExecution.mutateAsync({
        previewId: jobId, unit: selectedUnit,
        confirmation: executionConfirmation,
      });
      setExecutionJobId(response.job_id);
      setExecutionConfirmation('');
      toast.success(`安全执行任务 #${response.job_id} 已提交 Worker`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '执行请求被拒绝');
    }
  };

  const recoverOriginal = async () => {
    if (!canRecover || executionJobId === null) return;
    try {
      const response = await recoverExecution.mutateAsync({
        executionId: executionJobId, confirmation: recoveryConfirmation,
      });
      setExecutionJobId(response.job_id);
      setRecoveryConfirmation('');
      resetCleanup();
      toast.success(`恢复任务 #${response.job_id} 已提交 Worker`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '恢复请求被拒绝');
    }
  };

  const cleanupCurrentUnit = async () => {
    if (!canCleanup || executionJobId === null) return;
    try {
      const response = await startCleanup.mutateAsync({
        executionId: executionJobId, confirmation: cleanupConfirmation,
      });
      setExpectedCleanupJobId(response.job_id);
      setCleanupConfirmation('');
      setCleanupReviewOpen(false);
      void refetchExecution();
      toast.success(`独立清理任务 #${response.job_id} 已提交 Worker`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '清理请求被拒绝');
    }
  };

  const recoverCurrentCleanup = async () => {
    if (!canRecoverCleanup || !executionStatus?.cleanup) return;
    try {
      const response = await recoverCleanup.mutateAsync({
        cleanupId: executionStatus.cleanup.job_id, confirmation: cleanupRecoveryConfirmation,
      });
      setExpectedCleanupJobId(response.job_id);
      setCleanupRecoveryConfirmation('');
      void refetchExecution();
      toast.success(`清理恢复任务 #${response.job_id} 已提交 Worker`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '清理恢复请求被拒绝');
    }
  };

  return (
    <>
      {invalidExecutionId && (
        <p className="nfc-v2-batch-error" role="alert">
          执行任务编号无效，请从<Link to="/tasks">任务中心</Link>重新打开对应任务。
        </p>
      )}
      {executionJobId !== null && (
        <p className="nfc-form-note">
          当前整理任务 #{executionJobId} ·{' '}
          <Link to={`/tasks?task=${executionJobId}`}>查看任务记录</Link>
          {' '}· 刷新页面后可继续核查、清理或恢复，无需重新扫描。
        </p>
      )}
      <DataPanel title="智能媒体整理 · 只读分析"
        description="识别作者、合集和作品边界；按 V1.6 规则预览平铺、编号和分组。默认只读；仅管理员启用独立安全开关后才可逐作品确认执行。"
        className="nfc-v2-batch-media-panel nfc-tool-workbench">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <span>选择扫描范围</span>
            <DirectoryPicker multiple={false} value={selection} disabled={busy}
              placeholder="选择月份、日期、作者、合集或独立作品目录"
              onChange={changeSelection} />
            <small>递归发现独立作品；只扫描允许的目录，受保护的来源路径会被排除。</small>
          </div>
          <div className="nfc-v2-batch-notice" role="note">
            <ConsoleIcon name="shield-check" size={19} />
            <div>
              <strong>先只读预览，执行必须单独授权</strong>
              <p>扫描阶段绝不修改 NAS 文件。执行还需要管理员启用独立开关、确认指定作品，并通过冻结清单、身份校验和 Worker 租约。</p>
            </div>
          </div>
          <div className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={enqueue.isPending} disabled={busy}
              leadingIcon={<ConsoleIcon name="file-search" size={17} />}
              onClick={() => { void start(); }}>开始只读扫描</ConsoleButton>
            {isRunning(data?.status) && (
              <ConsoleButton disabled={cancel.isPending}
                onClick={() => { void stop(); }}>取消扫描</ConsoleButton>
            )}
          </div>
        </div>
      </DataPanel>

      {jobId !== null && (
        <DataPanel title="后台扫描任务" variant="dense"
          className="nfc-v2-batch-media-panel"
          action={<span className="nfc-panel-count">任务 #{jobId}</span>}
          description="任务由后台 Worker 执行，离开页面不影响扫描。">
          {data ? (
            <>
              <TaskProgress status={data.status} showDetails progress={{
                current: data.progress.current, total: data.progress.total,
                percent: null, message: data.progress.message,
              }} />
              {data.status === 'failed' && (
                <p className="nfc-v2-batch-error" role="alert">
                  扫描失败：{data.error || '请查看 Worker 日志'}
                </p>
              )}
            </>
          ) : (
            <p className="nfc-form-note" role="status">
              {isError ? getStructuredApiError(error).message :
                isFetching ? '正在查询后台任务…' : '任务排队中…'}
            </p>
          )}
        </DataPanel>
      )}

      {summary && data?.status === 'completed' && (
        <DataPanel title="目录整理分析报告" variant="dense"
          className="nfc-v2-batch-media-panel"
          description="此处为只读分析。只有单独选择作品并输入对应确认码，才会提交执行任务。"
          action={<span className="nfc-panel-count">{summary.unit_count.toLocaleString()} 个整理单元</span>}>
          <div className="nfc-v2-batch-media-stats" role="status">
            <span>扫描 <strong>{summary.unit_count.toLocaleString()}</strong></span>
            <span>待整理 <strong>{summary.ready_count.toLocaleString()}</strong></span>
            <span>待确认 <strong>{summary.blocked_count.toLocaleString()}</strong></span>
            <span>已整理 <strong>{summary.already_organized_count.toLocaleString()}</strong></span>
            <span>跳过 <strong>{summary.skipped_count.toLocaleString()}</strong></span>
            <span>预计移动 <strong>{summary.needed_moves.toLocaleString()}</strong></span>
            <span>预计改名 <strong>{summary.renamed_count.toLocaleString()}</strong></span>
          </div>
          <div className="nfc-v2-batch-field">
            <label htmlFor="semantic-media-status-filter">筛选状态</label>
            <select id="semantic-media-status-filter" value={statusFilter}
              onChange={event => { setStatusFilter(event.target.value); setPage(1); }}>
              <option value="all">全部</option>
              <option value="ready">待整理（{summary.ready_count}）</option>
              <option value="blocked">待检查（{summary.blocked_count}）</option>
              <option value="already_organized">已整理（{summary.already_organized_count}）</option>
              <option value="skipped">跳过（{summary.skipped_count}）</option>
            </select>
          </div>
          {!data.units.length ? (
            <ConsoleEmpty title="当前筛选没有目录" description="可以调整状态筛选或重新选择扫描范围。" />
          ) : (
            <div className="nfc-v2-batch-media-scroll">
              <table className="nfc-v2-batch-media-table">
                <caption className="nfc-v2-batch-media-sr-only">智能媒体整理逐目录只读预览</caption>
                <thead>
                  <tr><th scope="col">整理单元</th><th scope="col">状态</th>
                    <th scope="col">媒体数量</th><th scope="col">预计动作</th>
                    <th scope="col">目标目录与样例</th></tr>
                </thead>
                <tbody>
                  {data.units.map(item => {
                    const [status, label] = unitStatus(item);
                    return (
                      <tr key={item.unit}>
                        <td><CodePath value={item.unit} /></td>
                        <td><StatusBadge status={status} label={label} /></td>
                        <td>{item.totals.P}P / {item.totals.V}V / {item.totals.Other} Other</td>
                        <td>{item.needed_moves.toLocaleString()} 次路径调整
                          <small>{item.renamed_count.toLocaleString()} 次改名</small></td>
                        <td className="nfc-v2-batch-media-reason">
                          <div>{kindDescription(item)}</div>
                          {item.groups.map(group => (
                            <div key={group.destination}>
                              <CodePath value={group.name} />
                              <small> · {group.count} 个，{group.bytes.toLocaleString()} 字节</small>
                            </div>
                          ))}
                          {item.sample_moves.slice(0, 5).map((move, i) => (
                            <div key={move.source + i} className="nfc-form-note">
                              <CodePath value={move.source} /> → <CodePath value={move.target} />
                            </div>
                          ))}
                          {item.truncated && <small>只显示部分映射示例；统计包含该单元的全部媒体</small>}
                          {item.mapping_id && (
                            <div>
                              <ConsoleButton size="sm" variant="secondary"
                                onClick={() => {
                                  setMappingSelection({ unit: item.unit, mappingId: item.mapping_id! });
                                  setMappingPage(1);
                                }}>
                                查看完整映射（{item.total_proposals.toLocaleString()}）
                              </ConsoleButton>
                            </div>
                          )}
                          {item.conflicts.map((reason, i) => (
                            <p key={i} role="alert" className="nfc-v2-batch-error">阻止原因：{reason}</p>
                          ))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <ConsolePagination page={page} pageSize={pageSize} total={data.filtered_total}
            pageSizes={[10, 25, 50, 100]}
            onChange={(next, size) => { setPage(next); setPageSize(size); }} />
          <p className="nfc-form-note">预览不会移动文件。任何阻止项都必须先解决；不能跳过冲突强制执行。</p>
        </DataPanel>
      )}

      {mappingSelection && (
        <DataPanel title="完整源 → 目标映射" variant="dense"
          className="nfc-v2-batch-media-panel"
          action={<ConsoleButton size="sm" variant="ghost"
            onClick={() => { setMappingSelection(null); setMappingPage(1); }}>关闭</ConsoleButton>}
          description={<><CodePath value={mappingSelection.unit} /> · 完整映射分页展示，不含可变文件身份信息。</>}>
          {mappingLoadFailed ? (
            <p className="nfc-v2-batch-error" role="alert">
              {getStructuredApiError(mappingLoadError).message || '无法读取完整映射'}
            </p>
          ) : mappingFetching && !mappingData ? (
            <p className="nfc-form-note" role="status">正在读取完整映射…</p>
          ) : mappingData ? (
            <>
              <p className="nfc-form-note">
                共 {mappingData.total_moves.toLocaleString()} 条映射 · 第 {mappingData.page} 页
              </p>
              <div className="nfc-v2-batch-media-scroll">
                <table className="nfc-v2-batch-media-table">
                  <caption className="nfc-v2-batch-media-sr-only">完整源文件与目标路径映射</caption>
                  <thead>
                    <tr><th scope="col">类型</th><th scope="col">源路径</th>
                      <th scope="col">目标路径</th><th scope="col">字节数</th></tr>
                  </thead>
                  <tbody>
                    {mappingData.moves.map((move, index) => (
                      <tr key={move.source + index}>
                        <td>{move.kind}</td>
                        <td><CodePath value={move.source} /></td>
                        <td><CodePath value={move.target} /></td>
                        <td>{move.bytes.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ConsolePagination page={mappingPage} pageSize={mappingPageSize}
                total={mappingData.total_moves} pageSizes={[25, 50, 100]}
                onChange={(next, size) => { setMappingPage(next); setMappingPageSize(size); }} />
            </>
          ) : null}
        </DataPanel>
      )}

      {summary && data?.status === 'completed' && (
        <DataPanel title="单个作品 · 安全确认执行" variant="dense"
          className="nfc-v2-batch-media-panel"
          description="每次仅处理一个已预览作品；重新校验和冻结后才允许 Worker 修改文件。">
          {data.units.some(row => row.status === 'ready' && row.groups.length > 0 &&
            !data.confirmation_tokens[row.unit]) && (
            <p className="nfc-form-note" role="status">
              部分分组作品尚未满足服务器执行条件。只有服务器提供执行确认码的作品可以提交。
            </p>
          )}
          {!data.execution_enabled ? (
            <p className="nfc-form-note" role="status">
              当前只读。执行功能默认关闭，需要管理员在部署端审核并同时开启独立开关和文件修改权限。
            </p>
          ) : summary.blocked_count > 0 ? (
            <p className="nfc-v2-batch-error" role="alert">
              预览中有 {summary.blocked_count} 个待检查目录，禁止绕过冲突执行。
            </p>
          ) : summary.ready_count === 0 ? (
            <p className="nfc-form-note">没有需要执行的作品。</p>
          ) : executionJobId !== null ? (
            <p className="nfc-form-note">执行任务 #{executionJobId} 已提交。下方可查看进度或申请恢复。</p>
          ) : (
            <div className="nfc-v2-batch-form">
              <div className="nfc-v2-batch-field">
                <label htmlFor="semantic-execution-unit">选择当前页待整理作品</label>
                <select id="semantic-execution-unit" value={selectedUnit}
                  disabled={busy || startExecution.isPending}
                  onChange={e => {
                    setSelectedUnit(e.target.value);
                    setExecutionConfirmation('');
                  }}>
                  <option value="">请选择一个作品目录</option>
                  {executableUnits.map(item => (
                    <option value={item.unit} key={item.unit}>{item.unit}</option>
                  ))}
                </select>
              </div>
              {readyUnit && expectedConfirmation && (
                <div className="nfc-v2-batch-field">
                  <label htmlFor="semantic-execution-confirmation">逐作品执行确认码</label>
                  <code>{expectedConfirmation}</code>
                  <input id="semantic-execution-confirmation"
                    value={executionConfirmation} autoComplete="off" spellCheck={false}
                    disabled={busy || startExecution.isPending}
                    placeholder="输入完整确认码"
                    onChange={e => setExecutionConfirmation(e.target.value)} />
                </div>
              )}
              <ConsoleButton variant="danger" loading={startExecution.isPending}
                disabled={!canExecute} onClick={() => { void executeCurrentUnit(); }}>
                确认并执行当前作品
              </ConsoleButton>
            </div>
          )}
        </DataPanel>
      )}

      {executionJobId !== null && (
        <DataPanel title="安全执行与恢复状态" variant="dense"
          className="nfc-v2-batch-media-panel"
          action={<span className="nfc-panel-count">任务 #{executionJobId}</span>}>
          {executionStatus ? (
            <>
              {executionStatus.status === 'completed' && !executionStatus.finalized ? (
                <StatusBadge status="paused" label={executionStatus.cleanup
                  ? '发布与清理待核验'
                  : executionStatus.publication_complete ? '已发布，待清理' : '已准备，待完成发布'} />
              ) : <TaskProgress status={executionStatus.status} showDetails progress={{
                current: executionStatus.progress.current,
                total: executionStatus.progress.total,
                percent: null,
                message: executionStatus.progress.message,
              }} />}
              <p className="nfc-form-note">
                目标：<CodePath value={executionStatus.unit} />
              </p>
              {executionStatus.status === 'failed' && (
                <p className="nfc-v2-batch-error" role="alert">
                  执行中断：{executionStatus.error || '请检查任务记录'}。不得手动修改暂存目录。
                </p>
              )}
              {executionStatus.manual_cleanup_required && executionStatus.publication_complete &&
                !executionStatus.cleanup && expectedCleanupJobId === null && (
                <p className="nfc-v2-batch-error" role="alert">
                  媒体文件已发布，但原始文件、旧分类目录与私有暂存文件均已保留，
                  等待人工核查清理。请核对下方清单，再单独确认清理；无需自行删除暂存文件。
                </p>
              )}
              {executionStatus.manual_cleanup_required && !executionStatus.publication_complete &&
                !executionStatus.cleanup && expectedCleanupJobId === null && (
                <p className="nfc-form-note" role="status">
                  文件已安全暂存，部分目标需要在独立确认后完成发布。请核对下方释放、发布与保留清单，再确认后续操作。
                </p>
              )}
              {executionStatus.manual_cleanup_required && !executionStatus.publication_complete && (
                <p className="nfc-form-note">
                  冻结计划中的待发布目标数：{executionStatus.deferred_publication_count.toLocaleString()}。
                  该数值不代表当前剩余进度，完成情况以最终核验为准。
                </p>
              )}
              {executionStatus.manual_cleanup_required && (executionStatus.cleanup || expectedCleanupJobId !== null) && (
                <p className="nfc-form-note" role="status">
                  {executionStatus.cleanup?.status === 'failed' ? '清理任务已中断。' : '已进入独立清理流程。'}
                  部分原始路径或暂存数据可能已清理，请以下方任务状态和核验结果为准。
                </p>
              )}
              {executionStatus.status === 'completed' &&
                !executionStatus.manual_cleanup_required && executionStatus.finalized && (
                <p className="nfc-form-note">
                  服务器已完成清理，并验证再次扫描为零路径调整、零改名。
                </p>
              )}
              {executionStatus.status === 'failed' &&
                executionStatus.recovery_of_job_id == null && executionStatus.execution_enabled && (
                <div className="nfc-v2-batch-form">
                  <div className="nfc-v2-batch-field">
                    <label htmlFor="semantic-recovery-confirmation">人工恢复确认码</label>
                    <code>{recoveryToken}</code>
                    <input id="semantic-recovery-confirmation"
                      value={recoveryConfirmation} autoComplete="off"
                      spellCheck={false} disabled={recoverExecution.isPending}
                      onChange={e => setRecoveryConfirmation(e.target.value)}
                      placeholder="输入完整恢复确认码" />
                  </div>
                  <ConsoleButton variant="danger" disabled={!canRecover}
                    loading={recoverExecution.isPending}
                    onClick={() => { void recoverOriginal(); }}>
                    使用原冻结清单申请安全恢复
                  </ConsoleButton>
                  <p className="nfc-form-note">
                    仅在原始冻结清单和暂存身份可以核验时才会恢复；否则停止并要求人工检查。
                  </p>
                </div>
              )}
            </>
          ) : (
            <div>
              <p className="nfc-form-note" role={executionLoadFailed ? 'alert' : 'status'}>
                {executionLoadFailed ? getStructuredApiError(executionLoadError).message :
                  '正在核验执行任务并查询 Worker 状态…'}
              </p>
              {executionLoadFailed && (
                <ConsoleButton variant="secondary" onClick={() => { void refetchExecution(); }}>
                  重新读取执行任务
                </ConsoleButton>
              )}
            </div>
          )}
        </DataPanel>
      )}

      {executionJobId !== null && executionStatus &&
        (cleanupReviewAvailable || executionStatus.cleanup || expectedCleanupJobId !== null) && (
        <DataPanel title="独立清理与恢复" variant="dense"
          className="nfc-v2-batch-media-panel"
          description="核对原始路径、暂存文件、最终目标与保留项后，单独确认剩余发布和清理。完成以服务器验证零变更复扫为准。">
          <p className="nfc-form-note">整理单元：<CodePath value={executionStatus.unit} /></p>
          {expectedCleanupJobId !== null && executionStatus.cleanup?.job_id !== expectedCleanupJobId && (
            <p className="nfc-form-note" role="status">
              清理任务 #{expectedCleanupJobId} 已提交，正在查询 Worker 状态…
            </p>
          )}
          {executionLoadFailed && (
            <p className="nfc-v2-batch-error" role="alert">
              {getStructuredApiError(executionLoadError).message || '无法更新清理任务状态'}
            </p>
          )}
          {executionStatus.cleanup && (
            <>
              <p className="nfc-form-note">
                清理任务 #{executionStatus.cleanup.job_id} ·{' '}
                <StatusBadge status={executionStatus.cleanup.status} />
              </p>
              {isRunning(executionStatus.cleanup.status) && (
                <p className="nfc-form-note" role="status">后台正在清理或核对恢复记录，完成前不能更改当前整理范围。</p>
              )}
              {executionStatus.cleanup.status === 'failed' && (
                <>
                  <p className="nfc-v2-batch-error" role="alert">
                    清理任务中断：{executionStatus.cleanup.error || '请检查任务记录'}
                  </p>
                  {executionStatus.cleanup.recovery_confirmation ? (
                    <div className="nfc-v2-batch-form">
                      <div className="nfc-v2-batch-field">
                        <label htmlFor="semantic-cleanup-recovery-confirmation">本次清理恢复确认码</label>
                        <code>{executionStatus.cleanup.recovery_confirmation}</code>
                        <input id="semantic-cleanup-recovery-confirmation"
                          value={cleanupRecoveryConfirmation} autoComplete="off" spellCheck={false}
                          disabled={busy} placeholder="输入服务器提供的完整恢复确认码"
                          onChange={event => setCleanupRecoveryConfirmation(event.target.value)} />
                      </div>
                      <ConsoleButton variant="danger" disabled={!canRecoverCleanup}
                        loading={recoverCleanup.isPending}
                        onClick={() => { void recoverCurrentCleanup(); }}>
                        确认并恢复本次清理
                      </ConsoleButton>
                    </div>
                  ) : (
                    <p className="nfc-form-note">服务器尚未提供可用的恢复确认码，请保留现有文件并检查任务记录。</p>
                  )}
                </>
              )}
              {executionStatus.cleanup.status === 'completed' && executionStatus.finalized && (
                <p className="nfc-form-note" role="status">清理完成；服务器已确认零路径调整、零改名。</p>
              )}
            </>
          )}
          {cleanupReviewAvailable && !cleanupReviewOpen && (
            <ConsoleButton variant="secondary" disabled={busy}
              onClick={() => {
                setCleanupPage(1);
                setCleanupConfirmation('');
                setCleanupReviewOpen(true);
              }}>
              核查清理清单
            </ConsoleButton>
          )}
          {cleanupReviewAvailable && cleanupReviewOpen && (
            <>
              {cleanupPlanFailed ? (
                <div>
                  <p className="nfc-v2-batch-error" role="alert">
                    {getStructuredApiError(cleanupPlanError).message || '无法核查清理清单'}
                  </p>
                  <ConsoleButton disabled={busy || cleanupPlanFetching}
                    onClick={() => { setCleanupConfirmation(''); void refetchCleanupPlan(); }}>
                    重新核查清单
                  </ConsoleButton>
                </div>
              ) : cleanupPlanFetching && !cleanupPlan ? (
                <p className="nfc-form-note" role="status">正在读取并校验冻结清理清单…</p>
              ) : cleanupPlan ? (
                <>
                  <SemanticCleanupPlanInventory plan={cleanupPlan}
                    page={cleanupPage} pageSize={cleanupPageSize} busy={busy || cleanupPlanFetching}
                    onPageChange={(next, size) => {
                      setCleanupConfirmation('');
                      setCleanupPage(next);
                      setCleanupPageSize(size);
                    }} />
                  <div className="nfc-v2-batch-form">
                    <div className="nfc-v2-batch-field">
                      <label htmlFor="semantic-cleanup-confirmation">独立清理确认码</label>
                      <code>{cleanupPlan.confirmation}</code>
                      <input id="semantic-cleanup-confirmation"
                        value={cleanupConfirmation} autoComplete="off" spellCheck={false}
                        disabled={busy || cleanupPlanFetching} placeholder="核对清单后输入完整清理确认码"
                        onChange={event => setCleanupConfirmation(event.target.value)} />
                    </div>
                    <p className="nfc-form-note">
                      确认后将按清单释放占用路径、从已核验暂存文件完成目标发布，再清理多余原始路径和暂存数据。
                      清单中标为保留的文件与目标目录会保留。Worker 会再次核验权限、文件身份和执行记录。
                    </p>
                    <ConsoleButton variant="danger" disabled={!canCleanup}
                      loading={startCleanup.isPending}
                      onClick={() => { void cleanupCurrentUnit(); }}>
                      {cleanupPlan.total_deferred_publications > 0 || cleanupPlan.total_released_original_links > 0
                        ? '确认并完成发布与清理' : '确认并提交独立清理'}
                    </ConsoleButton>
                  </div>
                </>
              ) : null}
            </>
          )}
        </DataPanel>
      )}
    </>
  );
};
