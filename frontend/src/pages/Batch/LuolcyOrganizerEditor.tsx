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
import { luolcyApi, type LuolcyPackagePreview } from '../../api/luolcy';

const inProgress = (status: string | undefined) =>
  status === 'queued' || status === 'running' ||
  status === 'cancel_requested' || status === 'paused';

const packageStatus = (row: LuolcyPackagePreview): [string, string] => {
  if (row.status === 'blocked') return ['failed', '需要人工检查'];
  if (row.status === 'ready') return ['ready', '待整理'];
  if (row.status === 'already_organized') return ['completed', '已整理'];
  return ['skipped', '无需处理'];
};

const operationText = (row: LuolcyPackagePreview) => {
  if (row.operation === 'flatten_pure_media') return '纯媒体平铺到资源包根目录';
  if (row.operation === 'bucket_pure_media') return '纯媒体超过 200 个，按 P/V 分组';
  if (row.operation === 'sort_mixed_media') return '混合媒体分类到 P/V/Other';
  return row.reason === 'already_flat' ? '纯媒体已平铺' : '没有待整理文件';
};

export const LuolcyOrganizerEditor: React.FC = () => {
  const toast = useConsoleToast();
  const [selection, setSelection] = useState('');
  const [jobId, setJobId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const enqueue = useMutation({ mutationFn: luolcyApi.startPreview });
  const cancel = useMutation({ mutationFn: tasksApi.cancelTask });
  const { data, isError, error, isFetching } = useQuery({
    queryKey: ['luolcyPreview', jobId, page, pageSize],
    queryFn: () => luolcyApi.getPreview(jobId!, page, pageSize),
    enabled: jobId !== null,
    refetchInterval: (query) => inProgress(query.state.data?.status) ? 1300 : false,
  });
  const busy = enqueue.isPending || inProgress(data?.status) ||
    (jobId !== null && data == null);
  const summary = data?.summary;
  const changeSelection = (next: string | string[]) => {
    if (busy) return;
    setSelection(Array.isArray(next) ? next[0] || '' : next);
    setJobId(null);
    setPage(1);
  };
  const start = async () => {
    const chosen = selection.trim();
    if (!chosen.startsWith('/')) {
      toast.error('请选择 Luolcy、月份、日期、作者或资源包的绝对目录');
      return;
    }
    if (busy) return;
    setJobId(null);
    setPage(1);
    try {
      const result = await enqueue.mutateAsync(chosen);
      setJobId(result.job_id);
      toast.success(`Luolcy 只读预览任务 #${result.job_id} 已加入 Worker 队列`);
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '无法启动 Luolcy 预览');
    }
  };
  const stop = async () => {
    if (jobId === null || !inProgress(data?.status) || cancel.isPending) return;
    try {
      await cancel.mutateAsync(jobId);
      toast.success('已请求取消 Luolcy 只读预览');
    } catch (e: unknown) {
      toast.error(getStructuredApiError(e).message || '取消预览失败');
    }
  };

  return (
    <>
      <DataPanel title="Luolcy 专用整理 · 只读预览"
        description="规则固定不可配置；当前版本只生成检查报告，不移动或删除 NAS 文件。"
        className="nfc-v2-batch-media-panel nfc-tool-workbench">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <span>选择扫描范围</span>
            <DirectoryPicker multiple={false} value={selection} disabled={busy}
              placeholder="选择 /data/Else/Luolcy 或其中的月份、日期、作者、资源包"
              onChange={changeSelection} />
            <small>支持 Luolcy / 年月 / 年月日 / 作者 / 资源包；只允许该库下的固定层级。</small>
          </div>
          <div className="nfc-v2-batch-notice" role="note">
            <ConsoleIcon name="shield-check" size={19} />
            <div>
              <strong>资源包及上级目录始终保持不变</strong>
              <p>纯图片或纯视频不超过 200 个时平铺到资源包根目录；超过 200 个按 P/V 每组最多 200 个分类；
                混合文件放 P/V/Other。文件夹名称包含实际数量和大小，冲突需要人工检查。
                这里只扫描并显示计划，不开放实际移动。</p>
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
        <DataPanel title="Luolcy 后台扫描任务" variant="dense"
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
          description="结果仅供核对；不会自动修改文件。"
          action={<span className="nfc-panel-count">{summary.package_count.toLocaleString()} 个资源包</span>}>
          <div className="nfc-v2-batch-media-stats" role="status">
            <span>已扫描 <strong>{summary.package_count.toLocaleString()}</strong></span>
            <span>待整理 <strong>{summary.ready_count.toLocaleString()}</strong></span>
            <span>冲突 <strong>{summary.blocked_count.toLocaleString()}</strong></span>
            <span>已整理 <strong>{summary.already_organized_count.toLocaleString()}</strong></span>
            <span>跳过 <strong>{summary.skipped_count.toLocaleString()}</strong></span>
            <span>预计移动 <strong>{summary.needed_moves.toLocaleString()}</strong></span>
          </div>
          {!data.packages.length ? (
            <ConsoleEmpty title="当前范围没有可显示的资源包"
              description="可以选择更高一级 Luolcy/月份目录，或检查路径结构。" />
          ) : (
            <div className="nfc-v2-batch-media-scroll">
              <table className="nfc-v2-batch-media-table">
                <caption className="nfc-v2-batch-media-sr-only">Luolcy 资源包逐包只读整理预览</caption>
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
            total={summary.package_count} pageSizes={[10, 25, 50, 100]}
            onChange={(next, size) => { setPage(next); setPageSize(size); }} />
          <p className="nfc-form-note">
            下一阶段将单独加入带冻结、实时校验、无覆盖移动、空目录清理与中断恢复的执行流程。
          </p>
        </DataPanel>
      )}
    </>
  );
};
