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
import { media_packageApi, type MediaPackagePreview } from '../../api/media_package';

const inProgress = (status: string | undefined) =>
  status === 'queued' || status === 'running' ||
  status === 'cancel_requested' || status === 'paused';

const packageStatus = (row: MediaPackagePreview): [string, string] => {
  if (row.status === 'blocked') return ['failed', '需要人工检查'];
  if (row.status === 'ready') return ['ready', '待整理'];
  if (row.status === 'already_organized') return ['completed', '已整理'];
  return ['skipped', '无需处理'];
};

const operationText = (row: MediaPackagePreview) => {
  if (row.operation === 'flatten_pure_media') return '纯媒体平铺到资源包根目录';
  if (row.operation === 'bucket_pure_media') return '纯媒体超过 200 个，按 P/V 分组';
  if (row.operation === 'sort_mixed_media') return '混合媒体分类到 P/V/Other';
  return row.reason === 'already_flat' ? '纯媒体已平铺' : '没有待整理文件';
};

export const MediaPackageOrganizerEditor: React.FC = () => {
  const toast = useConsoleToast();
  const [selection, setSelection] = useState('');
  const [jobId, setJobId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);\n  const [statusFilter, setStatusFilter] = useState("all");
  const [executionJobId, setExecutionJobId] = useState<number | null>(null);
  const [executionConfirmation, setExecutionConfirmation] = useState('');
  const enqueue = useMutation({ mutationFn: media_packageApi.startPreview });
  const cancel = useMutation({ mutationFn: tasksApi.cancelTask });
  const executeMutation = useMutation({
    mutationFn: ({ previewId, confirmation }: { previewId: number; confirmation: string }) =>
      media_packageApi.startExecution(previewId, confirmation),
  });
  const { data: executionJob, isError: executionFailedToLoad, error: executionLoadError } = useQuery({
    queryKey: ['media_packageExecution', executionJobId],
    queryFn: () => media_packageApi.getExecution(executionJobId!),
    enabled: executionJobId !== null,
    refetchInterval: (query) => inProgress(query.state.data?.status) ? 1500 : false,
  });
  const { data, isError, error, isFetching } = useQuery({
    queryKey: ['media_packagePreview', jobId, page, pageSize, statusFilter],
    queryFn: () => media_packageApi.getPreview(jobId!, page, pageSize, statusFilter),
    enabled: jobId !== null,
    refetchInterval: (query) => inProgress(query.state.data?.status) ? 1300 : false,
  });
  const busy = enqueue.isPending || inProgress(data?.status) ||
    inProgress(executionJob?.status) ||
    (jobId !== null && data == null);
  const summary = data?.summary;
  const confirmationToken = jobId === null ? '' : `EXECUTE_MEDIA_PACKAGE_PREVIEW_${jobId}`;
  const canExecute = jobId !== null && data?.status === 'completed' &&
    summary != null && summary.ready_count > 0 && summary.blocked_count === 0 &&
    !busy && !executeMutation.isPending && executionJobId === null &&
    executionConfirmation === confirmationToken;
  const changeSelection = (next: string | string[]) => {
    if (busy) return;
    setSelection(Array.isArray(next) ? next[0] || '' : next);
    setJobId(null);
    setExecutionJobId(null);
    setExecutionConfirmation('');
    setPage(1);
  };
  const start = async () => {
    const chosen = selection.trim();
    if (!chosen.startsWith('/')) {
      toast.error('请选择 媒体资源包根目录、月份、日期、作者或资源包的绝对目录');
      return;
    }
    if (busy) return;
    setJobId(null);
    setExecutionJobId(null);
    setExecutionConfirmation('');
    setPage(1);
    try {
      const result = await enqueue.mutateAsync(chosen);
      setJobId(result.job_id);
      toast.success(`媒体资源包只读预览任务 #${result.job_id} 已加入 Worker 队列`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '无法启动 媒体资源包预览');
    }
  };
  const beginExecution = async () => {
    if (!canExecute || jobId === null) return;
    try {
      const result = await executeMutation.mutateAsync({
        previewId: jobId, confirmation: executionConfirmation,
      });
      setExecutionJobId(result.job_id);
      setExecutionConfirmation('');
      toast.success(`资源包安全执行任务 #${result.job_id} 已提交 Worker`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '安全执行任务无法启动');
    }
  };

  const stop = async () => {
    if (jobId === null || !inProgress(data?.status) || cancel.isPending) return;
    try {
      await cancel.mutateAsync(jobId);
      toast.success('已请求取消 媒体资源包只读预览');
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '取消预览失败');
    }
  };

  return (
    <>
      <DataPanel title="媒体资源包整理"
        description="先只读预览并检查冲突；只有管理员完成精确确认，才会启动 Worker 实际整理。"
        className="nfc-v2-batch-media-panel nfc-tool-workbench">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <span>选择扫描范围</span>
            <DirectoryPicker multiple={false} value={selection} disabled={busy}
              placeholder="选择已配置的媒体资源包根目录，或其下的月份、日期、作者、资源包"
              onChange={changeSelection} />
            <small>支持 媒体资源包根目录 / 年月 / 年月日 / 作者 / 资源包；只允许该库下的固定层级。</small>
          </div>
          <div className="nfc-v2-batch-notice" role="note">
            <ConsoleIcon name="shield-check" size={19} />
            <div>
              <strong>资源包及上级目录始终保持不变</strong>
              <p>纯图片或纯视频不超过 200 个时平铺到资源包根目录；超过 200 个按 P/V 每组最多 200 个分类；
                混合文件放 P/V/Other。文件夹名称包含实际数量和大小，冲突需要人工检查。
                执行前重新校验文件身份；禁止覆盖，失败时保留原文件与恢复证据。</p>
            </div>
          </div>
          <div className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={enqueue.isPending} disabled={busy}
              leadingIcon={<ConsoleIcon name="file-search" size={17} />}
              onClick={() => { void start(); }}>开始只读扫描</ConsoleButton>
            {inProgress(data?.status) && (
              <ConsoleButton disabled={cancel.isPending}
                onClick={() => { void stop(); }}>取消扫描</ConsoleButton>
            )}
          </div>
        </div>
      </DataPanel>

      {jobId !== null && (
        <DataPanel title="资源包后台扫描任务" variant="dense"
          className="nfc-v2-batch-media-panel"
          action={<span className="nfc-panel-count">任务 #{jobId}</span>}
          description="按资源包独立扫描并写入分页报告；关闭页面不会停止 Worker。">
          {data ? (
            <>
              <TaskProgress status={data.status} showDetails progress={{
                current: data.progress.current, total: data.progress.total,
                percent: null, message: data.progress.message,
              }} />
              {data.progress.current_package && (
                <p className="nfc-form-note">
                  当前：<CodePath value={data.progress.current_package} />
                </p>
              )}
              {data.status === 'failed' && (
                <p role="alert" className="nfc-v2-batch-error">
                  扫描失败：{data.error || '请检查 Worker 日志'}
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
        <DataPanel title="资源包整理检查报告" variant="dense"
          className="nfc-v2-batch-media-panel"
          description="这些是只读预览结果；仅提交明确确认的执行请求才会修改文件。"
          action={<span className="nfc-panel-count">{summary.package_count.toLocaleString()} 个资源包</span>}>
          <div className="nfc-v2-batch-media-stats" role="status">
            <span>已扫描 <strong>{summary.package_count.toLocaleString()}</strong></span>
            <span>待整理 <strong>{summary.ready_count.toLocaleString()}</strong></span>
            <span>冲突 <strong>{summary.blocked_count.toLocaleString()}</strong></span>
            <span>已整理 <strong>{summary.already_organized_count.toLocaleString()}</strong></span>
            <span>跳过 <strong>{summary.skipped_count.toLocaleString()}</strong></span>
            <span>预计移动 <strong>{summary.needed_moves.toLocaleString()}</strong></span>
          </div>
          <div className="nfc-v2-batch-field">\n            <label htmlFor="media-package-status-filter">按状态筛选</label>\n            <select id="media-package-status-filter" value={statusFilter}\n              onChange={event => { setStatusFilter(event.target.value); setPage(1); }}>\n              <option value="all">全部</option>\n              <option value="blocked">冲突（{summary.blocked_count}）</option>\n              <option value="ready">待整理（{summary.ready_count}）</option>\n              <option value="already_organized">已整理（{summary.already_organized_count}）</option>\n              <option value="skipped">跳过（{summary.skipped_count}）</option>\n            </select>\n          </div>\n          {!data.packages.length ? (
            <ConsoleEmpty title="当前范围没有可显示的资源包"
              description="可以选择更高一级 资源包根目录或月份目录，或检查路径结构。" />
          ) : (
            <div className="nfc-v2-batch-media-scroll">
              <table className="nfc-v2-batch-media-table">
                <caption className="nfc-v2-batch-media-sr-only">媒体资源包逐包只读整理预览</caption>
                <thead>
                  <tr><th scope="col">资源包</th><th scope="col">状态</th>
                    <th scope="col">文件</th><th scope="col">预计移动</th>
                    <th scope="col">预览与冲突</th></tr>
                </thead>
                <tbody>
                  {data.packages.map(row => {
                    const [status, label] = packageStatus(row);
                    return (
                      <tr key={row.package}>
                        <td><CodePath value={row.package} /></td>
                        <td><StatusBadge status={status} label={label} /></td>
                        <td>{row.total_files.toLocaleString()}</td>
                        <td>{row.needed_moves.toLocaleString()}</td>
                        <td className="nfc-v2-batch-media-reason">
                          <div>{operationText(row)}</div>
                          {(row.resolved_collision_count || 0) > 0 && (
                            <small>已自动避让 {row.resolved_collision_count} 个同名文件</small>
                          )}
                          {(row.renamed_count || 0) > 0 && (
                            <small>将统一编号 / 改名 {row.renamed_count} 个文件</small>
                          )}
                          {row.sample_moves.slice(0, 3).map((move, i) => (
                            <div key={move.source + i} className="nfc-form-note">
                              {move.original_relative_path || move.source} → {move.target_name || move.target}
                            </div>
                          ))}
                          {row.groups.map(group => (
                            <div key={group.destination}><CodePath value={group.name} /></div>
                          ))}
                          {row.conflicts.slice(0, 3).map((conflict, i) => (
                            <p key={i} role="alert">
                              冲突：{conflict.reason}{conflict.detail ? ` · ${conflict.detail}` : ''}
                            </p>
                          ))}
                          {row.conflicts.length > 3 && <p>还有 {row.conflicts.length - 3} 项冲突</p>}
                          {row.truncated && <small>文件示例已截断，未影响数量统计</small>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <ConsolePagination page={page} pageSize={pageSize}
            total={data.filtered_total} pageSizes={[10, 25, 50, 100]}
            onChange={(next, size) => { setPage(next); setPageSize(size); }} />
          <p className="nfc-form-note">
            执行使用冻结清单、Worker 租约、逐文件重新校验和禁止覆盖的移动操作；
            只有源目录真正为空才进行删除。操作中断可按同一任务清单恢复。
          </p>
        </DataPanel>
      )}

      {jobId !== null && data?.status === 'completed' && summary && (
        <DataPanel title="确认 资源包安全执行" variant="dense"
          className="nfc-v2-batch-media-panel"
          description="执行将真正移动文件并清理已确认的空子目录。需要管理员权限和 ALLOW_MUTATION / ALLOW_DELETE 开关。">
          {summary.blocked_count > 0 ? (
            <p role="alert" className="nfc-v2-batch-error">
              发现 {summary.blocked_count.toLocaleString()} 个冲突资源包，请先人工处理并重新扫描。
              禁止跳过冲突而直接执行整个范围。
            </p>
          ) : summary.ready_count === 0 ? (
            <p className="nfc-form-note">没有待整理的资源包，无须执行。</p>
          ) : executionJobId === null ? (
            <div className="nfc-v2-batch-form">
              <p className="nfc-form-note">
                即将处理 {summary.ready_count.toLocaleString()} 个待整理资源包，
                预计移动 {summary.needed_moves.toLocaleString()} 个文件。
                为防止误操作，请完整输入下方确认码，提交后不能自动撤销。
              </p>
              <div className="nfc-v2-batch-field">
                <label htmlFor="media_package-execution-confirmation">执行确认码</label>
                <code>{confirmationToken}</code>
                <input id="media_package-execution-confirmation" type="text"
                  autoComplete="off" spellCheck={false}
                  value={executionConfirmation}
                  onChange={event => setExecutionConfirmation(event.target.value)}
                  placeholder="输入完整确认码" disabled={busy || executeMutation.isPending} />
              </div>
              <ConsoleButton variant="danger" disabled={!canExecute}
                loading={executeMutation.isPending}
                onClick={() => { void beginExecution(); }}>
                确认并执行 媒体资源包整理
              </ConsoleButton>
            </div>
          ) : (
            <div role="status">
              <p>执行任务 #{executionJobId}</p>
              {executionJob ? (
                <>
                  <TaskProgress status={executionJob.status} showDetails progress={{
                    current: executionJob.progress.current,
                    total: executionJob.progress.total,
                    percent: null,
                    message: executionJob.progress.message,
                  }} />
                  {executionJob.progress.package && (
                    <p className="nfc-form-note">
                      当前资源包：{executionJob.progress.package}
                    </p>
                  )}
                  {executionJob.status === 'failed' && (
                    <p role="alert" className="nfc-v2-batch-error">
                      执行中断：{executionJob.error || '请检查任务日志'}。
                      不要手动删除正在使用的中间目录；须先检查恢复清单。
                    </p>
                  )}
                  {executionJob.status === 'completed' && (
                    <p className="nfc-form-note">整理任务已完成，建议重新进行一次只读扫描核对结果。</p>
                  )}
                </>
              ) : (
                <p className="nfc-form-note">
                  {executionFailedToLoad ? getStructuredApiError(executionLoadError).message :
                    '正在查询执行任务…'}
                </p>
              )}
            </div>
          )}
        </DataPanel>
      )}
    </>
  );
};
