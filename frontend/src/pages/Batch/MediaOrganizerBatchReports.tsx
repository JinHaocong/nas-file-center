import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { TaskProgress } from '../../components/tasks/TaskProgress';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { DataPanel } from '../../components/ui/DataPanel';
import { MediaThumbnail, ThumbnailSwitch } from '../../components/ui/MediaThumbnail';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useDisplayPreferences } from '../../contexts/DisplayPreferencesContext';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';

import { getStructuredApiError } from '../../api/errors';
import {
  mediaOrganizerBatchApi, type MediaBatchOutcome, type MediaBatchPreview,
  type MediaBatchPreviewUnit, type MediaBatchResult, type OrganizerJobId,
} from '../../api/mediaOrganizerBatch';

import { useResponsive } from '../../hooks/useResponsive';
import { formatBytes } from '../../utils/format';

const panelClass = 'nfc-v2-batch-media-panel nfc-v2-batch-organizer-report';
const previewLabels = {
  ready: '待整理', blocked: '冲突', skipped: '无需处理', already_organized: '已整理',
  needs_assignment: '待确认归属',
};
const previewTones = {
  ready: 'ready', blocked: 'partial', skipped: 'skipped', already_organized: 'completed',
  needs_assignment: 'partial',
} satisfies Record<MediaBatchPreviewUnit['status'], string>;
const conflictLabels: Readonly<Record<string, string>> = {
  target_path_exists: '目标路径已存在',
  target_directory_exists: '目标目录已存在',
  existing_bucket_name_requires_review: '发现占用目标的旧分类目录',
  legacy_numbered_bucket_requires_review: '发现需要检查的编号分类目录',
};
const outcomes = {
  success: { label: '成功', tone: 'completed' },
  skipped: { label: '跳过', tone: 'skipped' },
  conflict: { label: '冲突', tone: 'partial' },
  failed: { label: '失败', tone: 'failed' },
} satisfies Record<MediaBatchOutcome, { label: string; tone: string }>;
const resultStatuses: readonly MediaBatchOutcome[] = ['success', 'skipped', 'conflict', 'failed'];
const mappingKindLabels = { P: '图片', V: '视频', Other: '其他', Directory: '目录' };

type OpenUnitDetails = (row: MediaBatchPreviewUnit, opener: HTMLButtonElement) => void;

/** Render each unit's destinations, reasons and detail actions in either layout. */
function PreviewUnitDetails({ row, onDetails }: { row: MediaBatchPreviewUnit; onDetails: OpenUnitDetails }) {
  const reason = ['blocked', 'needs_assignment', 'skipped'].includes(row.status) ? row.reason : null;
  if (!row.groups.length && !row.conflicts.length && !reason && !row.loose_id && !row.mapping_id) return null;

  return (
    <div className="nfc-v2-batch-organizer-unit-detail">
      {row.groups.map(group => (
        <div key={group.destination}>
          <CodePath value={group.name} />{' '}
          <small>{group.count} 个 · {formatBytes(group.bytes)}</small>
        </div>
      ))}
      {row.conflicts.length > 0 ? row.conflicts.map((conflict, index) => {
        const target = conflict.target ?? conflict.directory;
        return (
          <p className="nfc-v2-batch-error" key={index}>
            <span>{conflictLabels[conflict.reason] ?? conflict.reason}</span>
            {target && <> <CodePath value={target} /></>}
            {!!conflict.existing?.length && <> <small>{conflict.existing.join('、')}</small></>}
          </p>
        );
      }) : reason && <p>{reason}</p>}
      {row.loose_id && (
        <ConsoleButton size="sm" variant="secondary" onClick={event => onDetails(row, event.currentTarget)}>
          查看散件并选择归属
        </ConsoleButton>
      )}
      {row.mapping_id && (
        <ConsoleButton size="sm" variant="secondary" onClick={event => onDetails(row, event.currentTarget)}>
          查看完整映射（{row.total_proposals.toLocaleString()}）
        </ConsoleButton>
      )}
    </div>
  );
}

/** Name the actual media present without synthesizing a filename or destination. */
function unitMediaLabel(row: MediaBatchPreviewUnit) {
  if (row.operation === 'promote_repeated_archive_children') {
    if (row.sample_moves?.some(move => move.kind !== 'Directory')) {
      return `整体上提 ${row.needed_moves.toLocaleString()} 项内容`;
    }
    return `整体上提 ${row.needed_moves.toLocaleString()} 个子目录`;
  }
  const counts = [];
  if (row.totals.P) counts.push(`${row.totals.P.toLocaleString()} 张图片`);
  if (row.totals.V) counts.push(`${row.totals.V.toLocaleString()} 段视频`);
  if (row.totals.Other) counts.push(`${row.totals.Other.toLocaleString()} 个其他文件`);
  return counts.join(' · ') || '0 个文件';
}

/** Preserve the complete unit path for inspection while keeping gallery captions readable. */
function unitName(path: string) {
  return path.split('/').filter(Boolean).pop() ?? path;
}

/** Render the selected unit using only paths reported by its verified preview. */
function UnitInspection({ row, onDetails, panelRef }: {
  row: MediaBatchPreviewUnit;
  onDetails: OpenUnitDetails;
  panelRef: React.Ref<HTMLElement>;
}) {
  const sample = row.sample_moves?.find(move => move.source !== move.target);
  const archiveLift = row.operation === 'promote_repeated_archive_children';
  return (
    <section ref={panelRef} className="nfc-unit-inspection" aria-label="所选目录整理详情" id="organizer-unit-inspection">
      <div className="nfc-unit-inspection-heading">
        <h3><ConsoleIcon name="folder-open" size={19} />{unitName(row.unit)}</h3>
        <StatusBadge status={previewTones[row.status]} label={previewLabels[row.status]} />
      </div>
      <CodePath value={row.unit} />
      <div className="nfc-unit-facts">
        <span>{unitMediaLabel(row)}</span>
        {archiveLift ? <span>保留子目录内部结构</span> : <>
          {row.total_bytes !== undefined && <span>{formatBytes(row.total_bytes)}</span>}
          <span>移动 {row.needed_moves.toLocaleString()} · 改名 {row.renamed_count.toLocaleString()}</span>
          {row.wrapper_cleanup_count !== undefined && <span>清空旧分类 {row.wrapper_cleanup_count}</span>}
        </>}
      </div>
      {sample && (
        <dl className="nfc-unit-path-comparison" aria-label={archiveLift ? '目录上提示例' : '文件路径调整示例'}>
          <div><dt>当前路径</dt><dd><CodePath value={sample.source} /></dd></div>
          <div><dt>整理后路径</dt><dd><CodePath value={sample.target} /></dd></div>
        </dl>
      )}
      <PreviewUnitDetails row={row} onDetails={onDetails} />
    </section>
  );
}

/** Display a preview's aggregated totals and the current page of independent units. */
export function MediaOrganizerPreviewReport({ preview, selected, onSelect, onDetails, action, children, footer }: {
  preview: MediaBatchPreview;
  selected?: MediaBatchPreviewUnit;
  onSelect: (row: MediaBatchPreviewUnit) => void;
  onDetails: OpenUnitDetails;
  action: React.ReactNode;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const { showThumbnails } = useDisplayPreferences();
  const { isMobile } = useResponsive();
  const inspectionRef = useRef<HTMLElement>(null);
  const revealAfterSelection = useRef(false);
  const selectedIndex = preview.units.findIndex(row => row.unit === selected?.unit);
  const columns = showThumbnails ? 2 : 1;
  const insertAfter = isMobile && selectedIndex >= 0
    ? Math.min(preview.units.length - 1, selectedIndex + (columns - 1 - selectedIndex % columns))
    : -1;

  /** 补偿展开位置变化，只在详情标题被导航挡住或离开视口时滚动。 */
  function revealInspection() {
    const panel = inspectionRef.current;
    if (!panel) return;
    const { top } = panel.getBoundingClientRect();
    if (top < 72 || top > window.innerHeight - 128) {
      panel.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  useLayoutEffect(() => {
    if (isMobile && revealAfterSelection.current) revealInspection();
    revealAfterSelection.current = false;
  }, [isMobile, selected?.unit]);

  /** 等选中行完成布局再判断详情是否需要滚入视口。 */
  function selectUnit(row: MediaBatchPreviewUnit) {
    if (isMobile) {
      if (row.unit === selected?.unit) revealInspection();
      else revealAfterSelection.current = true;
    }
    onSelect(row);
  }

  const summary = preview.summary;
  if (!summary) return null;
  const inspector = selected && <UnitInspection key={selected.unit} row={selected}
    onDetails={onDetails} panelRef={inspectionRef} />;

  return (
    <DataPanel title="整理预览" variant="dense" className={panelClass} action={<ThumbnailSwitch />}>
      <div className="nfc-unit-summarybar">
        <div className="nfc-unit-summary">
        <strong>{summary.unit_count.toLocaleString()} 个整理单元</strong>
        <span>{summary.file_count.toLocaleString()} 个文件</span>
        {summary.total_bytes !== undefined && <span>{formatBytes(summary.total_bytes)}</span>}
        <span>待整理 {summary.ready_count}</span><span>冲突 {summary.blocked_count}</span>
        <span>已整理 {summary.already_organized_count}</span><span>跳过 {summary.skipped_count}</span>
        {!!summary.needs_assignment_count && <span>待归属作者 {summary.needs_assignment_count}</span>}
        </div>
        <details className="nfc-unit-totals">
        <summary>变更统计</summary>
        <div className="nfc-unit-facts">
          {summary.totals && <span>图片 {summary.totals.P} · 视频 {summary.totals.V} · 其他 {summary.totals.Other}</span>}
          <span>预计移动 {summary.needed_moves.toLocaleString()}</span>
          <span>预计改名 {summary.renamed_count.toLocaleString()}</span>
          {summary.wrapper_cleanup_count !== undefined && <span>预计清空旧分类 {summary.wrapper_cleanup_count}</span>}
        </div>
        </details>
      </div>
      {children}
      {preview.units.length > 0 ? (
        <>
          <ul className={'nfc-unit-gallery' + (showThumbnails ? '' : ' is-compact')} role="list" aria-label="逐目录整理预览">
            {preview.units.map((row, index) => {
              const sample = row.sample_moves?.find(move => move.kind === 'P') ??
                row.sample_moves?.find(move => move.kind === 'V');
              return (
                <React.Fragment key={preview.job_id + '/' + row.unit}>
                  <li>
                    <button type="button" className="nfc-unit-card" aria-pressed={selected?.unit === row.unit}
                      title={row.unit} aria-controls={inspector ? 'organizer-unit-inspection' : undefined}
                      onClick={() => selectUnit(row)}>
                      <MediaThumbnail path={row.unit} kind="directory" size="cover" representativeFile={sample?.source} />
                      <span className="nfc-unit-caption">
                        <strong>{unitName(row.unit)}</strong>
                        <small>{unitMediaLabel(row)}</small>
                        <StatusBadge status={previewTones[row.status]} label={previewLabels[row.status]} />
                      </span>
                    </button>
                  </li>
                  {index === insertAfter && <li className="nfc-unit-gallery-inspection" role="presentation">{inspector}</li>}
                </React.Fragment>
              );
            })}
          </ul>
          {insertAfter === -1 && inspector}
        </>
      ) : <ConsoleEmpty title="当前筛选没有整理单元" />}
      {footer}
      {action && <footer className="nfc-unit-confirmation">
        <span><strong>{summary.ready_count.toLocaleString()} 个目录可整理</strong>
          {summary.blocked_count > 0 && ` · ${summary.blocked_count} 个冲突待核对`}</span>
        {action}
      </footer>}
    </DataPanel>
  );
}

/** Read the selected unit's mapping independently of the preview table page. */
export function MediaOrganizerMappingReport({ previewId, mappingId, unit, onClose }: {
  previewId: OrganizerJobId;
  mappingId: string;
  unit: string;
  onClose: () => void;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const reportRef = useRef<HTMLDivElement>(null);
  const { data, error, isError } = useQuery({
    queryKey: ['mediaOrganizerMapping', previewId, mappingId, page, pageSize],
    queryFn: () => mediaOrganizerBatchApi.getMapping(previewId, mappingId, page, pageSize),
  });

  useEffect(() => {
    reportRef.current?.focus({ preventScroll: true });
    reportRef.current?.scrollIntoView?.({ block: 'start' });
  }, []);

  return (
    <div className="nfc-v2-batch-organizer-focus-region" ref={reportRef} tabIndex={-1}
      role="region" aria-label="完整源 → 目标映射">
      <DataPanel title="完整源 → 目标映射" variant="dense" className={panelClass}
        description={<CodePath value={unit} />}
        action={<ConsoleButton size="sm" variant="ghost" onClick={onClose}>关闭</ConsoleButton>}>
        {isError ? (
          <p className="nfc-v2-batch-error" role="alert">{getStructuredApiError(error).message || '无法读取完整映射'}</p>
        ) : data ? (
          <>
            <ResponsiveDataView
              desktop={<div className="nfc-v2-batch-media-scroll">
                <table className="nfc-v2-batch-media-table">
                  <caption className="nfc-v2-batch-media-sr-only">媒体文件位置调整明细</caption>
                  <thead><tr><th scope="col">类型</th><th scope="col">源路径</th>
                    <th scope="col">目标路径</th><th scope="col">大小</th></tr></thead>
                  <tbody>{data.moves.map(move => (
                    <tr key={move.source}>
                      <td>{move.kind === 'Directory' ? mappingKindLabels.Directory : move.kind}</td>
                      <td><CodePath value={move.source} /></td>
                      <td><CodePath value={move.target} /></td><td>{move.kind === 'Directory' ? '—' : formatBytes(move.bytes)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<ul className="nfc-v2-batch-organizer-records" role="list" aria-label="媒体文件位置调整明细">
                {data.moves.map(move => (
                  <li key={move.source}>
                    <div className="nfc-v2-batch-organizer-record-heading">
                      <strong className="nfc-v2-batch-organizer-kind">{mappingKindLabels[move.kind]}</strong>
                      {move.kind !== 'Directory' && <span>{formatBytes(move.bytes)}</span>}
                    </div>
                    <dl className="nfc-v2-batch-organizer-paths">
                      <div><dt>源路径</dt><dd><CodePath value={move.source} /></dd></div>
                      <div><dt>目标路径</dt><dd><CodePath value={move.target} /></dd></div>
                    </dl>
                  </li>
                ))}
              </ul>}
            />
            <ConsolePagination page={page} pageSize={pageSize} total={data.total_moves}
              pageSizes={[25, 50, 100]} onChange={(next, size) => { setPage(next); setPageSize(size); }} />
          </>
        ) : <p role="status">正在读取映射…</p>}
      </DataPanel>
    </div>
  );
}

/** Display durable progress and the success, skip, conflict and failure counts. */
export function MediaOrganizerResultReport({ report, children }: {
  report: MediaBatchResult;
  children: React.ReactNode;
}) {
  const cleanupMessage = {
    pending: '报告明细已排队回收，整理结果会保留。',
    released: '报告文件已回收，整理结果已保留。',
    missing: '报告文件已不存在，整理结果已保留。',
  };
  return (
    <DataPanel title="整理结果" variant="dense" className={panelClass}>
      <TaskProgress status={report.status} progress={{ ...report.progress, percent: null }} />
      {report.error && <p className="nfc-v2-batch-error" role="alert">{report.error}</p>}
      {report.report_cleanup_status && <p className="nfc-form-note" role="status">
        {cleanupMessage[report.report_cleanup_status]}
      </p>}
      <div className="nfc-v2-batch-media-stats" role="status">
        {resultStatuses.map(status => (
          <span key={status}>{outcomes[status].label} <strong>{report.summary[`${status}_count`].toLocaleString()}</strong></span>
        ))}
      </div>
      {report.items.length > 0 && (
        <ResponsiveDataView
          desktop={<div className="nfc-v2-batch-media-scroll">
            <table className="nfc-v2-batch-media-table">
              <caption className="nfc-v2-batch-media-sr-only">各整理单元结果</caption>
              <thead><tr><th scope="col">整理单元</th><th scope="col">状态</th><th scope="col">说明</th></tr></thead>
              <tbody>{report.items.map(row => (
                <tr key={row.unit}>
                  <td><CodePath value={row.unit} /></td>
                  <td><StatusBadge status={outcomes[row.status].tone} label={outcomes[row.status].label} /></td>
                  <td>{row.reason || '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>}
          mobile={<ul className="nfc-v2-batch-organizer-records" role="list" aria-label="各整理单元结果">
            {report.items.map(row => (
              <li key={row.unit}>
                <div><StatusBadge status={outcomes[row.status].tone} label={outcomes[row.status].label} /></div>
                <CodePath value={row.unit} />
                {row.reason && <p>{row.reason}</p>}
              </li>
            ))}
          </ul>}
        />
      )}
      {children}
    </DataPanel>
  );
}
