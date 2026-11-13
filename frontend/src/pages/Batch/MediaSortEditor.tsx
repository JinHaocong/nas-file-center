import React, { useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { mediaSortApi, type MediaSortPreview, type MediaSortRow } from '../../api/mediaSort';
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
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const mediaLabel = (kind: MediaSortRow['media_kind']) => kind === 'image' ? '图片 → P' : '视频 → V';

/** Only creates a read-only preview and a generic Move Plan draft. Never executes moves. */
export const MediaSortEditor: React.FC = () => {
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [directory, setDirectory] = useState('');
  const [preview, setPreview] = useState<MediaSortPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const previewKeyRef = useRef<string | null>(null);
  const previewGuard = useRef(false);
  const planGuard = useRef(false);
  const previewMutation = useMutation({ mutationFn: mediaSortApi.preview });
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });
  const draft = useMemo(() => buildMediaSortDraft(preview), [preview]);
  const busy = previewLoading || planLoading;
  const canPlan = Boolean(draft && !busy && !previewGuard.current &&
    !planGuard.current && previewKeyRef.current === directory.trim());
  const shown = preview?.items.slice((page - 1) * pageSize, page * pageSize) || [];

  const invalidatePreview = () => {
    previewKeyRef.current = null;
    setPreview(null);
    setPage(1);
  };
  const changeDirectory = (value: string | string[]) => {
    if (planGuard.current) return;
    setDirectory(Array.isArray(value) ? value[0] || '' : value);
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
    previewKeyRef.current = selected;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const result = await previewMutation.mutateAsync(selected);
      if (previewKeyRef.current !== selected) return;
      setPreview(result);
      if (result.conflict_count) {
        toast.error(`发现 ${result.conflict_count} 项冲突，请先解决后重新预览`);
      } else {
        toast.success(`找到 ${result.image_count} 张图片、${result.video_count} 个视频`);
      }
    } catch (error: unknown) {
      if (previewKeyRef.current === selected) {
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
    if (previewKeyRef.current !== directory.trim()) return;
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
        description="仅处理选中目录下的一级普通文件：图片移入 P、视频移入 V；不扫描子目录，不删除文件。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench nfc-v2-batch-media-panel">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <span>需要整理的当前目录</span>
            <DirectoryPicker multiple={false} value={directory} disabled={planLoading}
              placeholder="选择图片和视频混放的目录"
              onChange={changeDirectory} />
            <small>P、V 均位于选中目录之下；若不存在，执行 Move Plan 时自动创建。</small>
          </div>
          <div className="nfc-v2-batch-notice" role="note">
            <ConsoleIcon name="shield-check" size={19} />
            <div><strong>先预览，再生成 Move Plan</strong>
              <p>仅按文件扩展名识别媒体类型，不转码、不修改名称；跳过符号链接。
                目标已有同名文件（含大小写差异）会阻止创建整个计划，不会覆盖原文件。
                执行仍需在计划详情完成 Freeze → Validate → Execute。</p>
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
            <span>图片 <strong>{preview.image_count}</strong></span>
            <span>视频 <strong>{preview.video_count}</strong></span>
            <span>可移动 <strong>{preview.ready_count}</strong></span>
            <span>冲突 <strong>{preview.conflict_count}</strong></span>
          </div>
          {preview.items.length === 0 ? (
            <ConsoleEmpty title="当前目录没有待分类的图片或视频"
              description="只会处理当前目录下的一级普通媒体文件。" />
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
    </>
  );
};
