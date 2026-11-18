import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
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
import { mediaOrganizerApi, type SemanticUnitPreview } from '../../api/media_organizer';

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

/** Preview-first workflow. Execution is default-off and requires explicit unit approval. */
export const SemanticMediaOrganizerEditor: React.FC = () => {
  const toast = useConsoleToast();
  const [selection, setSelection] = useState('');
  const [jobId, setJobId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedUnit, setSelectedUnit] = useState('');
  const [executionConfirmation, setExecutionConfirmation] = useState('');
  const [executionJobId, setExecutionJobId] = useState<number | null>(null);
  const [recoveryConfirmation, setRecoveryConfirmation] = useState('');
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
  const cancel = useMutation({ mutationFn: tasksApi.cancelTask });
  const { data, isError, error, isFetching } = useQuery({
    queryKey: ['semanticMediaPreview', jobId, page, pageSize, statusFilter],
    queryFn: () => mediaOrganizerApi.getPreview(jobId!, page, pageSize, statusFilter),
    enabled: jobId !== null,
    refetchInterval: query => isRunning(query.state.data?.status) ? 1500 : false,
  });
  const { data: executionStatus, isError: executionLoadFailed,
    error: executionLoadError } = useQuery({
    queryKey: ['semanticMediaExecution', executionJobId],
    queryFn: () => mediaOrganizerApi.getExecution(executionJobId!),
    enabled: executionJobId !== null,
    refetchInterval: query => isRunning(query.state.data?.status) ? 1500 : false,
  });
  const busy = enqueue.isPending || isRunning(data?.status) ||
    isRunning(executionStatus?.status) || (jobId !== null && data == null);
  const summary = data?.summary;
  const readyUnit = data?.units.find(row => row.unit === selectedUnit &&
    row.status === 'ready');
  const expectedConfirmation = data?.confirmation_tokens?.[selectedUnit] || '';
  const canExecute = Boolean(data?.execution_enabled && data?.status === 'completed' &&
    summary && summary.blocked_count === 0 && readyUnit && expectedConfirmation &&
    executionConfirmation === expectedConfirmation && !busy &&
    !startExecution.isPending && executionJobId === null);
  const recoveryToken = executionJobId === null ? '' :
    `RECOVER_MEDIA_ORGANIZER_EXECUTION_${executionJobId}`;
  const canRecover = Boolean(data?.execution_enabled && executionJobId !== null &&
    executionStatus?.status === 'failed' &&
    executionStatus.recovery_of_job_id == null &&
    recoveryConfirmation === recoveryToken && !recoverExecution.isPending);

  const changeSelection = (next: string | string[]) => {
    if (busy) return;
    setSelection(Array.isArray(next) ? next[0] || '' : next);
    setJobId(null);
    setSelectedUnit('');
    setExecutionConfirmation('');
    setExecutionJobId(null);
    setRecoveryConfirmation('');
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
      toast.success(`恢复任务 #${response.job_id} 已提交 Worker`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '恢复请求被拒绝');
    }
  };

  return (
    <>
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

      {summary && data?.status === 'completed' && (
        <DataPanel title="单个作品 · 安全确认执行" variant="dense"
          className="nfc-v2-batch-media-panel"
          description="每次仅处理一个已预览作品；重新校验和冻结后才允许 Worker 修改文件。">
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
                  {data.units.filter(x => x.status === 'ready').map(item => (
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
              <TaskProgress status={executionStatus.status} showDetails progress={{
                current: executionStatus.progress.current,
                total: executionStatus.progress.total,
                percent: null,
                message: executionStatus.progress.message,
              }} />
              <p className="nfc-form-note">
                目标：<CodePath value={executionStatus.unit} />
              </p>
              {executionStatus.status === 'failed' && (
                <p className="nfc-v2-batch-error" role="alert">
                  执行中断：{executionStatus.error || '请检查任务记录'}。不得手动修改暂存目录。
                </p>
              )}
              {executionStatus.manual_cleanup_required && (
                <p className="nfc-v2-batch-error" role="alert">
                  媒体文件已发布，但旧分类目录与私有暂存文件均已保留，
                  等待人工核查清理。请不要自行删除暂存数据或将本次任务视为彻底完成。
                </p>
              )}
              {executionStatus.status === 'completed' &&
                !executionStatus.manual_cleanup_required && executionStatus.finalized && (
                <p className="nfc-form-note">
                  任务已核对完成，请重新只读扫描确认最终文件结构。
                </p>
              )}
              {executionStatus.status === 'failed' &&
                executionStatus.recovery_of_job_id == null && data?.execution_enabled && (
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
            <p className="nfc-form-note" role="status">
              {executionLoadFailed ? getStructuredApiError(executionLoadError).message :
                '正在查询 Worker 执行状态…'}
            </p>
          )}
        </DataPanel>
      )}
    </>
  );
};
