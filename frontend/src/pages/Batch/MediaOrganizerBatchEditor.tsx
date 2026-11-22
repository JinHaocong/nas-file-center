import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { DirectoryPicker } from '../../components/DirectoryPicker';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { DataPanel } from '../../components/ui/DataPanel';
import {
  MediaOrganizerMappingReport, MediaOrganizerPreviewReport, MediaOrganizerResultReport,
} from './MediaOrganizerBatchReports';

import { getStructuredApiError } from '../../api/errors';
import {
  mediaOrganizerBatchApi, organizerJobId, type MediaBatchPreviewUnit,
  type MediaPreviewFilter, type OrganizerJobId,
} from '../../api/mediaOrganizerBatch';
import type { TaskStatus } from '../../types/task';

const panelClass = 'nfc-v2-batch-media-panel';
const pageSizes = [10, 25, 50, 100];

/** Check whether the current background task can still change its result. */
function isActive(status?: TaskStatus): boolean {
  return status === 'queued' || status === 'running' || status === 'cancel_requested' || status === 'paused';
}

/** Select an organizing scope, review its preview, then submit the entire scope once. */
export function MediaOrganizerBatchEditor() {
  const [params, setParams] = useSearchParams();
  const savedPreviewId = organizerJobId(params, 'preview');
  const batchId = organizerJobId(params, 'batch');
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [action, setAction] = useState<'preview' | 'confirm' | null>(null);
  const [problem, setProblem] = useState('');
  const [previewPage, setPreviewPage] = useState({ page: 1, size: 25 });
  const [filter, setFilter] = useState<MediaPreviewFilter>('all');
  const [resultPage, setResultPage] = useState({ page: 1, size: 25 });
  const [mapping, setMapping] = useState<{ unit: string; id: string } | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => { inFlight.current?.abort(); }, []);

  const resultQuery = useQuery({
    queryKey: ['mediaOrganizerBatch', batchId, resultPage.page, resultPage.size],
    queryFn: () => mediaOrganizerBatchApi.getBatch(batchId!, resultPage.page, resultPage.size),
    enabled: batchId !== null,
    placeholderData: (previous, query) => query?.queryKey[1] === batchId ? previous : undefined,
    refetchInterval: query => isActive(query.state.data?.status) ? 1200 : false,
  });
  const result = resultQuery.data;
  const previewId = savedPreviewId ?? result?.preview_job_id ?? null;
  const previewQuery = useQuery({
    queryKey: ['mediaOrganizerPreview', previewId, previewPage.page, previewPage.size, filter],
    queryFn: () => mediaOrganizerBatchApi.getPreview(previewId!, previewPage.page, previewPage.size, filter),
    enabled: previewId !== null,
    placeholderData: (previous, query) => query?.queryKey[1] === previewId ? previous : undefined,
    refetchInterval: query => isActive(query.state.data?.status) ? 1200 : false,
  });
  const preview = previewQuery.data;
  const existingBatchId = preview?.batch_job_id;
  useEffect(() => {
    if (!existingBatchId || batchId) return;
    setParams(current => {
      const next = new URLSearchParams(current);
      next.set('batch', existingBatchId);
      return next;
    }, { replace: true });
  }, [batchId, existingBatchId, setParams]);

  const selection = selectedPath ?? result?.selection ?? preview?.selection ?? '';
  const scanning = (previewId !== null && previewQuery.isPending) || isActive(preview?.status);
  const organizing = (batchId !== null && resultQuery.isPending) || isActive(result?.status);
  const busy = action !== null || scanning || organizing;
  const invalidLink = (params.has('preview') && !savedPreviewId) || (params.has('batch') && !batchId);

  /** Only one user action can be submitted until its response is applied to the URL. */
  async function runAction(
    kind: NonNullable<typeof action>, fallback: string,
    submit: (signal: AbortSignal) => Promise<void>,
  ) {
    if (inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setAction(kind);
    setProblem('');
    try {
      await submit(controller.signal);
    } catch (error: unknown) {
      if (!controller.signal.aborted) setProblem(getStructuredApiError(error).message || fallback);
    } finally {
      inFlight.current = null;
      if (!controller.signal.aborted) setAction(null);
    }
  }

  /** Persist job IDs in the current URL so reloading reconnects to background work. */
  function showJobs(previewJobId: OrganizerJobId | null, batchJobId?: OrganizerJobId) {
    setParams(current => {
      const next = new URLSearchParams(current);
      next.set('operation', 'media-organize');
      next.delete('execution');
      next.delete('preview');
      next.delete('batch');
      if (previewJobId) next.set('preview', previewJobId);
      if (batchJobId) next.set('batch', batchJobId);
      return next;
    }, { replace: true });
  }

  /** Keep the selected directory and apply its new preview only after successful submission. */
  async function queuePreview(path: string, signal: AbortSignal) {
    setSelectedPath(path);
    const receipt = await mediaOrganizerBatchApi.startPreview(path);
    if (signal.aborted) return;
    setPreviewPage({ page: 1, size: 25 });
    setFilter('all');
    setMapping(null);
    setResultPage({ page: 1, size: 25 });
    setSelectedPath(null);
    showJobs(receipt.job_id);
  }

  /** A directory chosen in the picker immediately starts its recursive preview. */
  function chooseDirectory(value: string | string[]) {
    if (busy || inFlight.current) return;
    const path = (Array.isArray(value) ? value[0] ?? '' : value).trim();
    if (!path) {
      setSelectedPath('');
      setMapping(null);
      setProblem('');
      showJobs(null);
      return;
    }
    if (!path.startsWith('/')) {
      setProblem('请选择 NAS 上的绝对目录');
      return;
    }
    void runAction('preview', '无法开始目录扫描', signal => queuePreview(path, signal));
  }

  /** Confirm the entire reviewed preview and follow its existing or new batch. */
  function confirmBatch() {
    if (busy || selectedPath !== null || batchId || existingBatchId || !previewId || !preview?.execution_enabled ||
      preview.status !== 'completed' || preview.selection !== selection || !preview.summary?.ready_count) return;
    void runAction('confirm', '无法开始整理', async signal => {
      const receipt = await mediaOrganizerBatchApi.startBatch(previewId);
      if (!signal.aborted) showJobs(previewId, receipt.job_id);
    });
  }

  const currentPreview = selectedPath === null && preview?.selection === selection ? preview : undefined;
  const currentResult = selectedPath === null ? result : undefined;
  const canConfirm = currentPreview?.status === 'completed' &&
    currentPreview.execution_enabled && Boolean(currentPreview.summary?.ready_count) &&
    batchId === null && !existingBatchId;
  /** Open the full mapping for one preview row. */
  function openMapping(row: MediaBatchPreviewUnit) {
    if (row.mapping_id) setMapping({ unit: row.unit, id: row.mapping_id });
  }

  return (
    <>
      <DataPanel title="智能媒体整理" className={`${panelClass} nfc-tool-workbench`}
        description="选择文件夹后自动扫描子目录。查看预览后，一次确认即可整理所有可处理的单元。">
        <div className="nfc-v2-batch-form">
          <div className="nfc-v2-batch-field">
            <DirectoryPicker value={selection} onChange={chooseDirectory} disabled={busy}
              allowManualInput={false} placeholder="选择媒体所在的目录" />
          </div>
          {selection && (
            <div className="nfc-file-tool-primary-actions">
              <ConsoleButton variant="secondary" disabled={busy}
                onClick={() => chooseDirectory(selection)}>重新扫描</ConsoleButton>
            </div>
          )}
          {invalidLink && <p className="nfc-v2-batch-error" role="alert">整理任务编号无效</p>}
          {problem && <p className="nfc-v2-batch-error" role="alert">{problem}</p>}
        </div>
      </DataPanel>

      {(action === 'preview' || scanning || previewQuery.isError ||
        currentPreview?.status === 'failed' || currentPreview?.status === 'cancelled') && (
        <DataPanel title="目录扫描" variant="dense" className={panelClass}>
          {previewQuery.isError ? (
            <p role="alert">{getStructuredApiError(previewQuery.error).message || '无法读取预览'}</p>
          ) : currentPreview?.status === 'failed' ? (
            <p role="alert">{currentPreview.error || '目录扫描失败'}</p>
          ) : currentPreview?.status === 'cancelled' ? (
            <p role="status">目录扫描已取消</p>
          ) : currentPreview ? (
            <TaskProgress status={currentPreview.status} progress={{ ...currentPreview.progress, percent: null }} />
          ) : <p role="status">正在读取目录预览…</p>}
        </DataPanel>
      )}

      {currentResult ? (
        <MediaOrganizerResultReport report={currentResult}>
          <ConsolePagination page={resultPage.page} pageSize={resultPage.size}
            total={currentResult.filtered_total} pageSizes={pageSizes}
            onChange={(page, size) => setResultPage({ page, size })} />
        </MediaOrganizerResultReport>
      ) : batchId && selectedPath === null && (
        <DataPanel title="整理结果" variant="dense" className={panelClass}>
          {resultQuery.isError ? (
            <p role="alert">{getStructuredApiError(resultQuery.error).message || '无法读取整理结果'}</p>
          ) : <p role="status">正在读取整理进度…</p>}
        </DataPanel>
      )}

      {currentPreview?.status === 'completed' && currentPreview.summary && (
        <MediaOrganizerPreviewReport preview={currentPreview} onMapping={openMapping}
          action={canConfirm && (
            <ConsoleButton variant="primary" disabled={busy} loading={action === 'confirm'}
              onClick={confirmBatch}>确认整理全部</ConsoleButton>
          )}
          footer={<ConsolePagination page={previewPage.page} pageSize={previewPage.size}
            total={currentPreview.filtered_total} pageSizes={pageSizes}
            onChange={(page, size) => setPreviewPage({ page, size })} />}>
          {!currentPreview.execution_enabled && <p className="nfc-form-note">当前仅可预览。</p>}
          {currentPreview.summary.ready_count === 0 && <p className="nfc-form-note">没有可整理的单元。</p>}
          {canConfirm && currentPreview.summary.blocked_count > 0 && (
            <p className="nfc-form-note">有冲突的单元会列在结果中，其余可整理的单元会继续处理。</p>
          )}
          <div className="nfc-v2-batch-field">
            <label htmlFor="media-organizer-batch-filter">筛选状态</label>
            <select id="media-organizer-batch-filter" value={filter} onChange={event => {
              setFilter(event.target.value as MediaPreviewFilter);
              setPreviewPage(previous => ({ ...previous, page: 1 }));
            }}>
              <option value="all">全部</option>
              <option value="ready">待整理</option>
              <option value="blocked">冲突</option>
              <option value="already_organized">已整理</option>
              <option value="skipped">跳过</option>
            </select>
          </div>
        </MediaOrganizerPreviewReport>
      )}

      {previewId && mapping && currentPreview?.status === 'completed' && (
        <MediaOrganizerMappingReport key={mapping.id} previewId={previewId}
          mappingId={mapping.id} unit={mapping.unit} onClose={() => setMapping(null)} />
      )}
    </>
  );
}
