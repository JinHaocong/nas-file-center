import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  mediaSortApi, type MediaSortRow, type MediaSortSkipReason,
} from '../../api/mediaSort';
import { tasksApi } from '../../api/tasks';
import { getStructuredApiError } from '../../api/errors';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleCheckbox } from '../../components/ui/ConsoleCheckbox';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const mediaLabel = (kind: MediaSortRow['media_kind']) => kind === 'image' ? '图片 → P' : '视频 → V';
const previewKey = (directory: string, recursive: boolean, smartSkip: boolean) =>
  JSON.stringify([directory.trim(), recursive, smartSkip]);
const skipReasonLabel: Record<MediaSortSkipReason, string> = {
  pure_images: '纯图片，无需整理',
  pure_videos: '纯视频，无需整理',
  no_media: '当前层无媒体',
  preclassified: '现有 P/V 分类目录',
};
const isActive = (status?: string | null) =>
  status === 'queued' || status === 'running' || status === 'cancel_requested' || status === 'paused';

export const MediaSortEditor: React.FC = () => {
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [directory, setDirectory] = useState('');
  const [recursive, setRecursive] = useState(false);
  const [smartSkip, setSmartSkip] = useState(true);
  const [previewJobId, setPreviewJobId] = useState<number | null>(null);
  const [planJobId, setPlanJobId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [skipPage, setSkipPage] = useState(1);
  const [skipPageSize, setSkipPageSize] = useState(25);
  const previewKeyRef = useRef<string | null>(null);
  const previewGuard = useRef(false);
  const planGuard = useRef(false);
  const navigationRef = useRef<number | null>(null);
  const previewMutation = useMutation({ mutationFn: mediaSortApi.startPreview });
  const planMutation = useMutation({ mutationFn: mediaSortApi.createPlanFromPreview });
  const cancelMutation = useMutation({ mutationFn: tasksApi.cancelTask });

  const {
    data: previewResponse,
    isFetching: previewFetching,
    isError: previewFailedToLoad,
    error: previewLoadError,
  } = useQuery({
    queryKey: ['mediaSortPreviewJob', previewJobId, page, pageSize, skipPage, skipPageSize],
    queryFn: () => mediaSortApi.getPreview(previewJobId!, page, pageSize, skipPage, skipPageSize),
    enabled: previewJobId !== null,
    refetchInterval: (query) => isActive(query.state.data?.status) ? 1400 : false,
  });

  const { data: planJob } = useQuery({
    queryKey: ['mediaSortGeneratePlanJob', planJobId],
    queryFn: () => mediaSortApi.getPlanJob(planJobId!),
    enabled: planJobId !== null,
    refetchInterval: (query) => isActive(query.state.data?.status) ? 1200 : false,
  });

  useEffect(() => {
    if (planJob?.status === 'completed' && planJob.plan_id && navigationRef.current !== planJob.plan_id) {
      navigationRef.current = planJob.plan_id;
      toast.success(`移动计划 #${planJob.plan_id} 已创建，请冻结、校验后再执行`);
      navigate(`/plans/${planJob.plan_id}`);
    }
  }, [planJob?.status, planJob?.plan_id, navigate, toast]);

  const summary = previewResponse?.summary;
  const busy = previewMutation.isPending || planMutation.isPending ||
    (previewJobId !== null && previewResponse == null) ||
    (planJobId !== null && planJob == null) ||
    isActive(previewResponse?.status) || isActive(planJob?.status);
  const ready = previewResponse?.status === 'completed' && summary !== null && summary !== undefined;
  const canPlan = Boolean(ready && summary && summary.count > 0 && summary.conflict_count === 0 &&
    previewKeyRef.current === previewKey(directory, recursive, smartSkip) &&
    !planGuard.current && !previewGuard.current && !busy && planJobId === null);

  const invalidatePreview = () => {
    previewKeyRef.current = null;
    setPreviewJobId(null);
    setPlanJobId(null);
    navigationRef.current = null;
    setPage(1);
    setSkipPage(1);
  };
  const changeDirectory = (value: string | string[]) => {
    if (busy || planGuard.current) return;
    setDirectory(Array.isArray(value) ? value[0] || '' : value);
    invalidatePreview();
  };
  const changeRecursive = (enabled: boolean) => {
    if (busy) return;
    setRecursive(enabled);
    invalidatePreview();
  };
  const changeSmartSkip = (enabled: boolean) => {
    if (busy) return;
    setSmartSkip(enabled);
    invalidatePreview();
  };

  const generatePreview = async () => {
    if (previewGuard.current || planGuard.current || busy) return;
    const selected = directory.trim();
    if (!selected.startsWith('/')) {
      toast.error('请先选择有效的绝对目录路径');
      return;
    }
    invalidatePreview();
    const key = previewKey(selected, recursive, smartSkip);
    previewKeyRef.current = key;
    previewGuard.current = true;
    try {
      const result = await previewMutation.mutateAsync({
        parent: selected, recursive, smart_skip: smartSkip,
      });
      if (previewKeyRef.current !== key) return;
      setPreviewJobId(result.job_id);
      toast.success(`只读预览任务 #${result.job_id} 已加入 Worker 队列，可查看实时扫描进度`);
    } catch (error: unknown) {
      if (previewKeyRef.current === key) {
        invalidatePreview();
        toast.error(getStructuredApiError(error).message || '创建媒体扫描任务失败');
      }
    } finally {
      previewGuard.current = false;
    }
  };

  const createPlan = async () => {
    if (!previewJobId || !canPlan || planGuard.current) return;
    planGuard.current = true;
    try {
      const result = await planMutation.mutateAsync(previewJobId);
      setPlanJobId(result.job_id);
      toast.success(`移动计划生成任务 #${result.job_id} 已入队`);
    } catch (error: unknown) {
      toast.error(getStructuredApiError(error).message || '生成移动计划失败');
    } finally {
      planGuard.current = false;
    }
  };

  const cancelPreview = async () => {
    if (!previewJobId || !isActive(previewResponse?.status) || cancelMutation.isPending) return;
    try {
      await cancelMutation.mutateAsync(previewJobId);
      toast.success('已请求取消预览扫描，将在下一个检查点停止');
    } catch (error: unknown) {
      toast.error(getStructuredApiError(error).message || '取消预览失败');
    }
  };

  const renderStatus = (item: MediaSortRow) => (
    <StatusBadge status={item.conflict ? 'failed' : 'completed'}
      label={item.conflict ? item.conflict_reason || '目标冲突' : '可移动'} />
  );
  const skippedShown = previewResponse?.skipped_directories || [];
  const shown = previewResponse?.items || [];

  return (
    <>
      <DataPanel title="图片 / 视频自动分类"
        description={recursive
          ? '递归检查选中目录及其子目录：图片和视频分别归入每层目录自己的 P / V。'
          : '只处理当前目录一级文件，不扫描子目录。'}
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench nfc-v2-batch-media-panel">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <span>需要整理的当前目录</span>
            <DirectoryPicker multiple={false} value={directory} disabled={busy}
              placeholder="选择混放图片和视频的目录" onChange={changeDirectory} />
            <small>大目录将交给后台 Worker 逐层扫描；预览不修改源文件，不一次性传输所有路径。</small>
          </div>
          <label className="nfc-v2-batch-media-recursive">
            <ConsoleCheckbox checked={recursive} disabled={busy}
              onCheckedChange={changeRecursive} aria-label="递归处理子目录" />
            <span><strong>递归处理子目录</strong>
              <small>默认关闭。开启后每层目录各自使用 P/V，跳过已有 P、V 和数字后缀分类目录。</small>
            </span>
          </label>
          <label className="nfc-v2-batch-media-recursive">
            <ConsoleCheckbox checked={smartSkip} disabled={busy}
              onCheckedChange={changeSmartSkip} aria-label="智能跳过已整理目录" />
            <span><strong>智能跳过已整理目录（推荐）</strong>
              <small>默认开启。纯图片/纯视频目录保留原有名称；其他普通子目录仍继续检查。</small>
            </span>
          </label>
          <div className="nfc-v2-batch-notice" role="note">
            <ConsoleIcon name="shield-check" size={19} />
            <div><strong>先只读预览，再生成安全 Move Plan</strong>
              <p>目标 P/V 或文件重名时自动追加后缀，不覆盖任何原文件。
                实际移动仍需完成 Freeze → Validate → Execute。递归总扫描项数可能未知，
                因此扫描阶段显示实时计数而非虚构百分比；冻结、校验和执行会显示已处理项数。</p>
            </div>
          </div>
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewMutation.isPending} disabled={busy}
              leadingIcon={<ConsoleIcon name="file-search" size={17} />}
              onClick={() => { void generatePreview(); }}>开始预览扫描</ConsoleButton>
            {isActive(previewResponse?.status) && (
              <ConsoleButton disabled={cancelMutation.isPending}
                onClick={() => { void cancelPreview(); }}>取消扫描</ConsoleButton>
            )}
            {ready && summary && summary.count > 0 && (
              <ConsoleButton loading={planMutation.isPending} disabled={!canPlan}
                leadingIcon={<ConsoleIcon name="calendar" size={17} />}
                onClick={() => { void createPlan(); }}>
                生成移动 Plan（{summary.count.toLocaleString()} 项）
              </ConsoleButton>
            )}
          </ActionBar>
        </div>
      </DataPanel>

      {previewJobId !== null && (
        <DataPanel title="预览扫描进度" variant="dense"
          description="后台 Worker 逐目录检查；关闭页面不会停止扫描。"
          action={<span className="nfc-panel-count">任务 #{previewJobId}</span>}
          className="nfc-file-tool-result-panel nfc-v2-batch-media-panel">
          {previewResponse ? (
            <div className="nfc-v2-media-scan-progress" aria-live="polite">
              <TaskProgress progress={{
                current: previewResponse.progress.current,
                total: previewResponse.progress.total,
                percent: null,
                message: previewResponse.progress.message,
              }} status={previewResponse.status} showDetails />
              <div className="nfc-v2-batch-media-stats">
                <span>已检查条目 <strong>{(previewResponse.progress.scanned_entries || 0).toLocaleString()}</strong></span>
                <span>扫描目录 <strong>{(previewResponse.progress.scanned_directories || 0).toLocaleString()}</strong></span>
                <span>待移动 <strong>{(previewResponse.progress.candidate_count || 0).toLocaleString()}</strong></span>
                <span>待扫描目录 <strong>{(previewResponse.progress.pending_directories || 0).toLocaleString()}</strong></span>
              </div>
              {previewResponse.progress.current_directory && (
                <p className="nfc-form-note">当前目录：<CodePath value={previewResponse.progress.current_directory} /></p>
              )}
              {previewResponse.status === 'failed' && (
                <p role="alert" className="nfc-v2-batch-error">
                  扫描失败：{previewResponse.error || '请检查 Worker 日志或缩小扫描范围'}
                </p>
              )}
              {previewResponse.status === 'cancelled' && <p className="nfc-form-note">预览已取消，可重新开始。</p>}
            </div>
          ) : (
            <div className="nfc-form-note" role="status">
              {previewFailedToLoad ? getStructuredApiError(previewLoadError).message :
                previewFetching ? '正在读取扫描状态…' : '预览任务排队中…'}
            </div>
          )}
        </DataPanel>
      )}

      {planJobId !== null && (
        <DataPanel title="创建移动计划进度" variant="dense"
          description="将预览中的文件映射写入 Plan Draft；不会移动任何文件。"
          className="nfc-file-tool-result-panel nfc-v2-batch-media-panel">
          {planJob ? (
            <TaskProgress progress={{
              current: planJob.progress?.current || 0,
              total: planJob.progress?.total || 0,
              percent: null, message: planJob.progress?.message || null,
            }} status={planJob.status} showDetails />
          ) : <p className="nfc-form-note">正在读取任务状态…</p>}
          {planJob?.status === 'failed' && <p className="nfc-v2-batch-error" role="alert">
            生成计划失败：{planJob.error || '请查看任务中心'}
          </p>}
        </DataPanel>
      )}

      {ready && summary && (
        <DataPanel title="媒体分类预览" variant="dense"
          description="以下仅展示当前页的只读提议；预览没有新建目录或移动文件。"
          action={<span className="nfc-panel-count">{summary.count.toLocaleString()} 项</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel nfc-v2-batch-media-panel">
          <div className="nfc-v2-batch-media-stats" role="status">
            <span>扫描目录 <strong>{summary.scanned_directories.toLocaleString()}</strong></span>
            <span>图片 <strong>{summary.image_count.toLocaleString()}</strong></span>
            <span>视频 <strong>{summary.video_count.toLocaleString()}</strong></span>
            <span>可移动 <strong>{summary.ready_count.toLocaleString()}</strong></span>
            <span>冲突 <strong>{summary.conflict_count.toLocaleString()}</strong></span>
            <span>跳过目录 <strong>{summary.skipped_directory_count.toLocaleString()}</strong></span>
          </div>
          {summary.conflict_count > 0 && <p role="alert" className="nfc-v2-batch-error">
            有 {summary.conflict_count.toLocaleString()} 项目标冲突，不能生成 Plan；现有文件不会被覆盖。
          </p>}
          {summary.count === 0 ? (
            <ConsoleEmpty title="当前范围没有待分类的媒体文件"
              description="纯图片/纯视频目录已保留，详见下方跳过目录明细。" />
          ) : (
            <ResponsiveDataView
              desktop={<div className="nfc-v2-batch-media-scroll">
                <table className="nfc-v2-batch-media-table">
                  <caption className="nfc-v2-batch-media-sr-only">图片和视频目标位置预览</caption>
                  <thead><tr><th scope="col">类型</th><th scope="col">源文件</th>
                    <th scope="col">目标位置</th><th scope="col">状态</th></tr></thead>
                  <tbody>{shown.map(item => (
                    <tr key={item.source}>
                      <td>{mediaLabel(item.media_kind)}</td>
                      <td><CodePath value={item.source} /></td>
                      <td><CodePath value={item.target} muted={item.conflict} /></td>
                      <td>{renderStatus(item)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<div className="nfc-mobile-record-list nfc-v2-batch-media-mobile-list">
                {shown.map(item => (
                  <article className="nfc-rename-proposal-mobile-card" key={item.source}>
                    <div className="nfc-mobile-record-heading">
                      <span className="nfc-kind-badge">{mediaLabel(item.media_kind)}</span>
                      {renderStatus(item)}
                    </div>
                    <div className="nfc-plan-item-paths">
                      <div className="nfc-plan-item-path-row"><span>源文件</span><CodePath value={item.source}/></div>
                      <div className="nfc-plan-item-path-row"><span>目标</span><CodePath value={item.target} muted={item.conflict}/></div>
                    </div>
                  </article>
                ))}
              </div>}
            />
          )}
          <ConsolePagination page={page} pageSize={pageSize} total={summary.count}
            pageSizes={[10, 25, 50, 100]}
            onChange={(next, size) => { setPage(next); setPageSize(size); }} />
        </DataPanel>
      )}

      {ready && summary && summary.skipped_directory_count > 0 && (
        <DataPanel title="跳过目录明细" variant="dense"
          description="已分类目录不扫描，纯媒体或当前层无媒体的目录不产生移动计划。"
          action={<span className="nfc-panel-count">{summary.skipped_directory_count.toLocaleString()} 个目录</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel nfc-v2-batch-media-panel">
          <ResponsiveDataView
            desktop={<div className="nfc-v2-batch-media-scroll">
              <table className="nfc-v2-batch-media-table">
                <caption className="nfc-v2-batch-media-sr-only">跳过目录及原因</caption>
                <thead><tr><th scope="col">目录</th><th scope="col">原因</th><th scope="col">本层数量</th></tr></thead>
                <tbody>{skippedShown.map(item => (
                  <tr key={item.path}>
                    <td><CodePath value={item.path}/></td>
                    <td><StatusBadge status="skipped" label={skipReasonLabel[item.reason]}/></td>
                    <td>{item.reason === 'preclassified' ? '未扫描（保留原目录）' :
                      `图片 ${item.image_count} · 视频 ${item.video_count}`}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>}
            mobile={<div className="nfc-mobile-record-list nfc-v2-batch-media-mobile-list">
              {skippedShown.map(item => (
                <article className="nfc-rename-proposal-mobile-card" key={item.path}>
                  <StatusBadge status="skipped" label={skipReasonLabel[item.reason]}/>
                  <CodePath value={item.path}/>
                </article>
              ))}
            </div>}
          />
          <ConsolePagination page={skipPage} pageSize={skipPageSize}
            total={summary.skipped_directory_count} pageSizes={[10, 25, 50, 100]}
            onChange={(next, size) => { setSkipPage(next); setSkipPageSize(size); }} />
        </DataPanel>
      )}
    </>
  );
};
