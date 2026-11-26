import { useEffect, useLayoutEffect, useRef, useState } from 'react';
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
import { MediaOrganizerLooseFilesReport } from './MediaOrganizerLooseFilesReport';

import { getStructuredApiError } from '../../api/errors';
import {
  mediaOrganizerBatchApi, organizerJobId, type MediaBatchPreviewUnit,
  type MediaPreviewFilter, type OrganizerJobId,
} from '../../api/mediaOrganizerBatch';
import type { TaskStatus } from '../../types/task';

const panelClass = 'nfc-v2-batch-media-panel';
const pageSizes = [10, 25, 50, 100];
const previewFilters: readonly [MediaPreviewFilter, string][] = [
  ['all', '全部'], ['ready', '待整理'], ['blocked', '冲突'], ['already_organized', '已整理'],
  ['skipped', '跳过'], ['needs_assignment', '待确认归属'],
];

interface FilterHighlight { x: number; y: number; width: number; height: number }

/** Measure the current button so the active surface follows filtering and responsive wrapping. */
function OrganizerFilters({ value, counts, onChange, disabled }: {
  value: MediaPreviewFilter;
  counts: Record<MediaPreviewFilter, number | undefined>;
  onChange: (filter: MediaPreviewFilter) => void;
  disabled: boolean;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const active = useRef<HTMLButtonElement>(null);
  const [highlight, setHighlight] = useState<FilterHighlight | null>(null);
  const hasUnassigned = Boolean(counts.needs_assignment) || value === 'needs_assignment';

  useLayoutEffect(() => {
    const button = active.current;
    const container = bar.current;
    if (!button || !container) return;
    /** Publish geometry only when it changes, including after font measurements. */
    function measure() {
      if (!button) return;
      const next = { x: button.offsetLeft, y: button.offsetTop, width: button.offsetWidth, height: button.offsetHeight };
      setHighlight(previous => previous && previous.x === next.x && previous.y === next.y &&
        previous.width === next.width && previous.height === next.height ? previous : next);
    }
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    for (const candidate of container.querySelectorAll('button')) observer.observe(candidate);
    return () => observer.disconnect();
  }, [value, hasUnassigned]);

  return <div ref={bar} className="nfc-organizer-workspace-filters" id="media-organizer-batch-filter"
    data-highlight={Boolean(highlight)} role="group" aria-label="筛选状态">
    {highlight && <span aria-hidden="true" className="nfc-organizer-filter-highlight" style={{
      width: highlight.width, height: highlight.height, transform: `translate(${highlight.x}px, ${highlight.y}px)`,
    }} />}
    {previewFilters.filter(([key]) => key !== 'needs_assignment' || hasUnassigned)
      .map(([key, label]) => <button key={key} ref={value === key ? active : undefined} type="button"
        data-preview-filter={key} aria-pressed={value === key} disabled={disabled} onClick={() => onChange(key)}>
        {label} <span>{counts[key] ?? 0}</span>
      </button>)}
  </div>;
}

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
  const [inspectedUnit, setInspectedUnit] = useState<string | null>(null);
  const [action, setAction] = useState<'preview' | 'confirm' | null>(null);
  const [problem, setProblem] = useState('');
  const [previewPage, setPreviewPage] = useState({ page: 1, size: 25 });
  const [filter, setFilter] = useState<MediaPreviewFilter>('all');
  const [resultPage, setResultPage] = useState({ page: 1, size: 25 });
  const [assignmentBusy, setAssignmentBusy] = useState(false);
  const [assignmentDraft, setAssignmentDraft] = useState<{
    previewId: OrganizerJobId; detailId: string; planId: string;
  } | null>(null);
  const [details, setDetails] = useState<{
    previewId: OrganizerJobId; unit: string; id: string; kind: 'mapping' | 'loose';
  } | null>(null);
  const inFlight = useRef<AbortController | null>(null);
  const detailOpener = useRef<HTMLButtonElement | null>(null);

  useEffect(() => () => { inFlight.current?.abort(); }, []);

  const resultQuery = useQuery({
    queryKey: ['mediaOrganizerBatch', batchId, resultPage.page, resultPage.size],
    queryFn: () => mediaOrganizerBatchApi.getBatch(batchId!, resultPage.page, resultPage.size),
    enabled: batchId !== null,
    placeholderData: (previous, query) => query?.queryKey[1] === batchId ? previous : undefined,
    refetchInterval: query => {
      if (isActive(query.state.data?.status)) return 1200;
      return query.state.data?.report_cleanup_status === 'pending' ? 5000 : false;
    },
  });
  const result = resultQuery.data;
  // The batch determines whether its historical preview can still be read.
  const previewId = batchId && (!result || result.report_cleanup_status)
    ? null : savedPreviewId ?? result?.preview_job_id ?? null;
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

  const suggestedPaths = params.has('preview') || params.has('batch') || params.has('execution')
    ? [] : params.getAll('directory');
  const suggested = suggestedPaths.length === 1 ? suggestedPaths[0] : '';
  const suggestedValid = suggested.startsWith('/') && !suggested.startsWith('//') && !suggested.includes('\0') &&
    !suggested.split('/').some(part => part === '..' || part === '.');
  const selection = selectedPath ?? result?.selection ?? preview?.selection ?? (suggestedValid ? suggested : '');
  const scanning = (previewId !== null && previewQuery.isPending) || isActive(preview?.status);
  const organizing = (batchId !== null && resultQuery.isPending) || isActive(result?.status);
  const busy = action !== null || scanning || organizing || assignmentBusy;
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
      next.delete('directory');
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
    setInspectedUnit(null);
    setDetails(null);
    setResultPage({ page: 1, size: 25 });
    setSelectedPath(null);
    showJobs(receipt.job_id);
  }

  /** A directory chosen in the picker immediately starts its recursive preview. */
  function chooseDirectory(value: string | string[]) {
    if (busy || inFlight.current) return;
    const path = Array.isArray(value) ? value[0] ?? '' : value;
    if (!path) {
      setSelectedPath('');
      setDetails(null);
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
  const currentUnit = currentPreview?.units.find(row => row.unit === inspectedUnit) ?? currentPreview?.units[0];
  const currentDetails = details?.previewId === previewId && details?.unit === currentUnit?.unit ? details : null;
  const previewSummary = currentPreview?.summary;

  /** Switch the inspector and discard any detail report belonging to the previous unit. */
  function inspectUnit(row: MediaBatchPreviewUnit) {
    if (assignmentBusy) return;
    if (currentUnit?.unit !== row.unit) setDetails(null);
    setInspectedUnit(row.unit);
  }

  /** Open the paginated report attached to one preview row. */
  function openDetails(row: MediaBatchPreviewUnit, opener: HTMLButtonElement) {
    if (!previewId || assignmentBusy) return;
    const id = row.loose_id ?? row.mapping_id;
    if (!id) return;
    detailOpener.current = opener;
    setDetails({ previewId, unit: row.unit, id, kind: row.loose_id ? 'loose' : 'mapping' });
  }

  /** Return keyboard focus to the row that opened the report. */
  function closeDetails() {
    if (assignmentBusy) return;
    setDetails(null);
    const opener = detailOpener.current;
    // 窗口尺寸跨过断点后，详情可能已经移动到目录卡片所在的行。
    if (opener?.isConnected === false) {
      document.querySelector<HTMLButtonElement>('.nfc-unit-card[aria-pressed="true"]')?.focus();
    } else {
      opener?.focus();
    }
  }

  /** A different filter starts on page one and keeps detail tied to visible data. */
  function changeFilter(nextFilter: MediaPreviewFilter) {
    if (nextFilter === filter || assignmentBusy) return;
    setDetails(null);
    setInspectedUnit(null);
    setFilter(nextFilter);
    setPreviewPage(previous => ({ ...previous, page: 1 }));
  }

  const filterCounts = {
    all: previewSummary?.unit_count,
    ready: previewSummary?.ready_count,
    blocked: previewSummary?.blocked_count,
    already_organized: previewSummary?.already_organized_count,
    skipped: previewSummary?.skipped_count,
    needs_assignment: previewSummary?.needs_assignment_count,
  } satisfies Record<MediaPreviewFilter, number | undefined>;

  const detailReport = currentDetails?.kind === 'mapping' ? (
    <MediaOrganizerMappingReport key={`${currentDetails.previewId}:${currentDetails.id}`}
      previewId={currentDetails.previewId} mappingId={currentDetails.id} unit={currentDetails.unit}
      onClose={closeDetails} embedded />
  ) : currentDetails?.kind === 'loose' ? (
    <MediaOrganizerLooseFilesReport key={`${currentDetails.previewId}:${currentDetails.id}`}
      previewId={currentDetails.previewId} looseId={currentDetails.id} author={currentDetails.unit}
      disabled={busy} onClose={closeDetails} onDraftBusyChange={setAssignmentBusy}
      planId={assignmentDraft?.previewId === currentDetails.previewId && assignmentDraft.detailId === currentDetails.id
        ? assignmentDraft.planId : undefined}
      onDraftCreated={planId => setAssignmentDraft({
        previewId: currentDetails.previewId, detailId: currentDetails.id, planId,
      })} />
  ) : null;

  return (
    <>
      <section className="nfc-organizer-scope" aria-label="整理目录">
        <div className="nfc-organizer-scope-controls">
          <strong>整理目录</strong>
          <DirectoryPicker value={selection} onChange={chooseDirectory} disabled={busy}
            allowManualInput={false} placeholder="选择媒体所在的目录" />
          {selection && <ConsoleButton variant="secondary" disabled={busy}
            onClick={() => chooseDirectory(selection)}>{suggestedValid && !currentPreview ? '预览' : '重新扫描'}</ConsoleButton>}
        </div>
        {!selection && <p className="nfc-form-note">选择文件夹后自动扫描子目录。</p>}
        {invalidLink && <p className="nfc-v2-batch-error" role="alert">整理任务编号无效</p>}
        {suggestedPaths.length > 0 && !suggestedValid &&
          <p className="nfc-v2-batch-error" role="alert">目录入口无效，请重新选择目录。</p>}
        {problem && <p className="nfc-v2-batch-error" role="alert">{problem}</p>}
      </section>

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
          {currentResult.filtered_total > 0 && <ConsolePagination page={resultPage.page} pageSize={resultPage.size}
            total={currentResult.filtered_total} pageSizes={pageSizes}
            onChange={(page, size) => setResultPage({ page, size })} />}
        </MediaOrganizerResultReport>
      ) : batchId && selectedPath === null && (
        <DataPanel title="整理结果" variant="dense" className={panelClass}>
          {resultQuery.isError ? (
            <p role="alert">{getStructuredApiError(resultQuery.error).message || '无法读取整理结果'}</p>
          ) : <p role="status">正在读取整理进度…</p>}
        </DataPanel>
      )}

      {currentPreview?.status === 'completed' && currentPreview.summary && (
        <MediaOrganizerPreviewReport preview={currentPreview} selected={currentUnit} onSelect={inspectUnit} onDetails={openDetails}
          detail={detailReport} onDismissDetails={() => setDetails(null)} pending={previewQuery.isPlaceholderData}
          detailBusy={assignmentBusy}
          action={canConfirm && (
            <ConsoleButton variant="primary" disabled={busy} loading={action === 'confirm'}
              onClick={confirmBatch}>确认整理全部</ConsoleButton>
          )}
          footer={<ConsolePagination page={previewPage.page} pageSize={previewPage.size}
            total={currentPreview.filtered_total} pageSizes={pageSizes}
            onChange={(page, size) => {
              if (assignmentBusy) return;
              setDetails(null);
              setPreviewPage({ page, size });
            }} />}>
          {!currentPreview.execution_enabled && <p className="nfc-form-note">当前仅可预览。</p>}
          {currentPreview.summary.ready_count === 0 && <p className="nfc-form-note">没有可整理的单元。</p>}
          {!!currentPreview.summary.needs_assignment_count && (
            <p className="nfc-form-note">批量整理会跳过待确认归属的散件。可逐个作者选择文件和目标资源包。</p>
          )}
          <OrganizerFilters value={filter} counts={filterCounts} onChange={changeFilter} disabled={assignmentBusy} />
        </MediaOrganizerPreviewReport>
      )}
    </>
  );
}
