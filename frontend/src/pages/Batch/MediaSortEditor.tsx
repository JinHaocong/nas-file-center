import React, { useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { mediaSortApi, type MediaSortPreview, type MediaSortRow, type MediaSortSkipReason } from '../../api/mediaSort';
import { plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { buildMediaSortDraft } from '../../utils/mediaSortSafety';
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

/** Only creates a read-only preview and a generic Move Plan draft. Never executes moves. */
export const MediaSortEditor: React.FC = () => {
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [directory, setDirectory] = useState('');
  const [recursive, setRecursive] = useState(false);
  const [smartSkip, setSmartSkip] = useState(true);
  const [preview, setPreview] = useState<MediaSortPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [skipPage, setSkipPage] = useState(1);
  const [skipPageSize, setSkipPageSize] = useState(20);
  const previewKeyRef = useRef<string | null>(null);
  const previewGuard = useRef(false);
  const planGuard = useRef(false);
  const previewMutation = useMutation({ mutationFn: mediaSortApi.preview });
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });
  const draft = useMemo(() => buildMediaSortDraft(preview), [preview]);
  const busy = previewLoading || planLoading;
  const canPlan = Boolean(draft && !busy && !previewGuard.current &&
    !planGuard.current && previewKeyRef.current === previewKey(directory, recursive, smartSkip));
  const shown = preview?.items.slice((page - 1) * pageSize, page * pageSize) || [];
  const skippedShown = preview?.skipped_directories.slice(
    (skipPage - 1) * skipPageSize, skipPage * skipPageSize,
  ) || [];
  const alreadySorted = preview?.skipped_directories.filter(item =>
    item.reason === 'pure_images' || item.reason === 'pure_videos').length || 0;

  const invalidatePreview = () => {
    previewKeyRef.current = null;
    setPreview(null);
    setPage(1);
    setSkipPage(1);
  };
  const changeDirectory = (value: string | string[]) => {
    if (planGuard.current) return;
    setDirectory(Array.isArray(value) ? value[0] || '' : value);
    invalidatePreview();
  };

  const changeRecursive = (enabled: boolean) => {
    if (planGuard.current) return;
    setRecursive(enabled);
    invalidatePreview();
  };

  const changeSmartSkip = (enabled: boolean) => {
    if (planGuard.current) return;
    setSmartSkip(enabled);
    invalidatePreview();
  };

  const generatePreview = async () => {
    if (previewGuard.current || planGuard.current) return;
    const selected = directory.trim();
    if (!selected.startsWith('/')) {
      toast.error('请先选择有效的绝对目录路径');
      return;
    }
    invalidatePreview();
    const key = previewKey(selected, recursive, smartSkip);
    previewKeyRef.current = key;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const result = await previewMutation.mutateAsync({ parent: selected, recursive, smart_skip: smartSkip });
      if (previewKeyRef.current !== key) return;
      setPreview(result);
      if (result.conflict_count) {
        toast.error(`发现 ${result.conflict_count} 项冲突，请先解决后重新预览`);
      } else if (result.count === 0) {
        toast.success(`没有需要移动的媒体，已跳过 ${result.skipped_directory_count} 个目录`);
      } else {
        toast.success(`待移动图片 ${result.image_count} 张、视频 ${result.video_count} 个`);
      }
    } catch (error: unknown) {
      if (previewKeyRef.current === key) {
        invalidatePreview();
        toast.error(getStructuredApiError(error).message || '媒体分类预览失败');
      }
    } finally {
      previewGuard.current = false;
      setPreviewLoading(false);
    }
  };

  const createPlan = async () => {
    if (planGuard.current || previewGuard.current || !canPlan || !draft) return;
    // The response belongs to this exact directory input, not an earlier Preview.
    if (previewKeyRef.current !== previewKey(directory, recursive, smartSkip)) return;
    planGuard.current = true;
    setPlanLoading(true);
    try {
      const result = await planMutation.mutateAsync(draft);
      toast.success(`媒体分类计划 #${result.id} 已创建，请冻结并校验后执行`);
      navigate(`/plans/${result.id}`);
    } catch (error: unknown) {
      toast.error(getStructuredApiError(error).message || '创建分类计划失败');
    } finally {
      planGuard.current = false;
      setPlanLoading(false);
    }
  };

  const renderStatus = (item: MediaSortRow) => (
    <StatusBadge status={item.conflict ? 'failed' : 'completed'}
      label={item.conflict ? item.conflict_reason || '目标冲突' : '可移动'} />
  );

  return (
    <>
      <DataPanel title="图片 / 视频自动分类"
        description={recursive
          ? '递归检查选中目录及其子目录：每层文件分别放到本目录自己的 P / V 下。'
          : '仅处理选中目录下的一级普通文件：图片移入 P、视频移入 V；不扫描子目录。'}
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench nfc-v2-batch-media-panel">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <span>需要整理的当前目录</span>
            <DirectoryPicker multiple={false} value={directory} disabled={planLoading}
              placeholder="选择图片和视频混放的目录"
              onChange={changeDirectory} />
            <small>每个目录分别归类；目标 P/V 不存在时，执行 Move Plan 时自动创建。</small>
          </div>
          <label className="nfc-v2-batch-media-recursive">
            <ConsoleCheckbox checked={recursive} disabled={planLoading}
              onCheckedChange={changeRecursive} aria-label="递归处理子目录" />
            <span>
              <strong>递归处理子目录</strong>
              <small>默认关闭。开启后扫描所有下级目录，每个目录建立自己的 P/V；
                跳过已有的 P、V 和 P_数字、V_数字 分类目录。</small>
            </span>
          </label>
          <label className="nfc-v2-batch-media-recursive">
            <ConsoleCheckbox checked={smartSkip} disabled={planLoading}
              onCheckedChange={changeSmartSkip} aria-label="智能跳过已整理目录" />
            <span>
              <strong>智能跳过已整理目录（推荐）</strong>
              <small>默认开启。仅含图片或仅含视频的目录保持不变，已有的中文/小写目录名也保留；
                .DS_Store 和 Thumbs.db 不影响判断。纯媒体目录的普通子目录仍会递归检查。</small>
            </span>
          </label>
          <div className="nfc-v2-batch-notice" role="note">
            <ConsoleIcon name="shield-check" size={19} />
            <div><strong>先预览，再生成 Move Plan</strong>
              <p>只读取同一层的普通文件判断是否需要整理；同时有图片和视频时分类。
                若存在其他普通文件（除 .DS_Store、Thumbs.db），则保守地不判定为纯媒体目录。
                目标 P/V 已占用时使用 P_1/V_1 等名称，文件名冲突使用 _1、_2 等后缀；
                不覆盖原文件。移动仍需经 Freeze → Validate → Execute。</p>
            </div>
          </div>
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewLoading} disabled={planLoading}
              leadingIcon={<ConsoleIcon name="file-search" size={17} />}
              onClick={() => { void generatePreview(); }}>预览分类结果</ConsoleButton>
            {preview !== null && preview.count > 0 && (
              <ConsoleButton loading={planLoading} disabled={!canPlan}
                leadingIcon={<ConsoleIcon name="calendar" size={17} />}
                onClick={() => { void createPlan(); }}>
                生成移动 Plan（{preview.count} 项）
              </ConsoleButton>
            )}
          </ActionBar>
        </div>
      </DataPanel>
      {preview !== null && preview.conflict_count > 0 && (
        <div className="nfc-v2-batch-error" role="alert">
          检测到 {preview.conflict_count} 项目标冲突；请先处理 P / V 内的重名文件，再重新预览。
          现有文件不会被覆盖。
        </div>
      )}
      {preview !== null && (
        <DataPanel title="媒体分类预览" variant="dense"
          description="以下为只读文件移动提议；预览本身不会新建 P / V，也不会移动任何文件。"
          action={<span className="nfc-panel-count">{preview.count} 项</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel nfc-v2-batch-media-panel">
          <div className="nfc-v2-batch-media-stats" role="status" aria-live="polite">
            <span>扫描目录 <strong>{preview.scanned_directories}</strong></span>
            <span>图片 <strong>{preview.image_count}</strong></span>
            <span>视频 <strong>{preview.video_count}</strong></span>
            <span>可移动 <strong>{preview.ready_count}</strong></span>
            <span>冲突 <strong>{preview.conflict_count}</strong></span>
            <span>跳过目录 <strong>{preview.skipped_directory_count}</strong></span>
            {smartSkip && <span>已整理 <strong>{alreadySorted}</strong></span>}
          </div>
          {preview.items.length === 0 ? (
            <ConsoleEmpty
              title={alreadySorted > 0 ? "已整理的媒体目录无需再次分类" : "当前范围没有待分类的媒体文件"}
              description="可查看下方跳过目录和具体原因；当前预览不会移动文件。" />
          ) : (
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-batch-media-scroll">
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
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-batch-media-mobile-list">
                  {shown.map(item => (
                    <article className="nfc-rename-proposal-mobile-card" key={item.source}>
                      <div className="nfc-mobile-record-heading">
                        <span className="nfc-kind-badge">{mediaLabel(item.media_kind)}</span>
                        {renderStatus(item)}
                      </div>
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row"><span>源文件</span><CodePath value={item.source} /></div>
                        <div className="nfc-plan-item-path-row"><span>目标</span>
                          <CodePath value={item.target} muted={item.conflict} /></div>
                      </div>
                      {item.conflict && <p className="nfc-mobile-record-error">{item.conflict_reason}</p>}
                    </article>
                  ))}
                </div>
              }
            />
          )}
          <ConsolePagination page={page} pageSize={pageSize} total={preview.count}
            pageSizes={[10, 20, 50]} onChange={(next, size) => { setPage(next); setPageSize(size); }} />
        </DataPanel>
      )}
      {preview !== null && preview.skipped_directory_count > 0 && (
        <DataPanel title="跳过目录明细" variant="dense"
          description="按每层目录的实际普通文件判断。纯图片/纯视频保持原有目录名；
            无媒体目录不产生移动计划，已有 P/V 分类目录不递归。"
          action={<span className="nfc-panel-count">{preview.skipped_directory_count} 个目录</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel nfc-v2-batch-media-panel">
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-batch-media-scroll">
                <table className="nfc-v2-batch-media-table">
                  <caption className="nfc-v2-batch-media-sr-only">跳过目录及判定原因</caption>
                  <thead><tr><th scope="col">目录</th><th scope="col">跳过原因</th>
                    <th scope="col">本层文件</th></tr></thead>
                  <tbody>{skippedShown.map(item => (
                    <tr key={item.path}>
                      <td><CodePath value={item.path} /></td>
                      <td><StatusBadge status="skipped" label={skipReasonLabel[item.reason]} /></td>
                      <td>图片 {item.image_count} · 视频 {item.video_count}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            }
            mobile={
              <div className="nfc-mobile-record-list nfc-v2-batch-media-mobile-list">
                {skippedShown.map(item => (
                  <article className="nfc-rename-proposal-mobile-card" key={item.path}>
                    <div className="nfc-mobile-record-heading">
                      <StatusBadge status="skipped" label={skipReasonLabel[item.reason]} />
                    </div>
                    <CodePath value={item.path} />
                    <span className="nfc-form-note">
                      本层图片 {item.image_count} · 视频 {item.video_count}
                    </span>
                  </article>
                ))}
              </div>
            }
          />
          <ConsolePagination page={skipPage} pageSize={skipPageSize}
            total={preview.skipped_directory_count} pageSizes={[10, 20, 50]}
            onChange={(next, size) => { setSkipPage(next); setSkipPageSize(size); }} />
        </DataPanel>
      )}
    </>
  );
};
