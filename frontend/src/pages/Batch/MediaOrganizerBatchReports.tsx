import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { TaskProgress } from '../../components/tasks/TaskProgress';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleSheet } from '../../components/ui/ConsoleSheet';
import { DataPanel } from '../../components/ui/DataPanel';
import { MediaThumbnail, ThumbnailSwitch } from '../../components/ui/MediaThumbnail';
import { commonDirectoryPrefix, PathPrefixDisclosure, usePathPrefix } from '../../components/ui/PathPrefixDisclosure';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { OrganizerStructure } from './OrganizerStructure';

import { getStructuredApiError } from '../../api/errors';
import {
  mediaOrganizerBatchApi, type MediaBatchOutcome, type MediaBatchPreview,
  type MediaBatchPreviewUnit, type MediaBatchResult, type OrganizerJobId,
} from '../../api/mediaOrganizerBatch';

import { useDisplayPreferences } from '../../contexts/DisplayPreferencesContext';
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
const recycleLabels = { url_shortcut: '网络快捷方式', links_only: '纯链接文本', promotion: '推广文本', text_file: 'TXT 文本文件' };

type OpenUnitDetails = (row: MediaBatchPreviewUnit, opener: HTMLButtonElement) => void;

/** Render each unit's destinations, reasons and detail actions in either layout. */
function PreviewUnitDetails({ row, onDetails, groupsShown = false }: {
  row: MediaBatchPreviewUnit; onDetails: OpenUnitDetails; groupsShown?: boolean;
}) {
  const reason = ['blocked', 'needs_assignment', 'skipped'].includes(row.status) ? row.reason : null;
  const showGroups = !groupsShown && row.groups.length > 0;
  if (!showGroups && !row.conflicts.length && !reason && !row.loose_id) return null;

  return (
    <div className="nfc-v2-batch-organizer-unit-detail">
      {showGroups && <details className="nfc-organizer-destinations">
        <summary>查看全部目标分类（{row.groups.length.toLocaleString()}）</summary>
        <OrganizerDestinations groups={row.groups} />
      </details>}
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
    </div>
  );
}

/** Keep the full destination list available below the compact structure preview. */
function OrganizerDestinations({ groups }: { groups: MediaBatchPreviewUnit['groups'] }) {
  return <ul className="nfc-organizer-destinations">
    {groups.map(group => (
      <li key={group.destination}>
        <div><strong>{group.name}</strong><small>{group.count.toLocaleString()} 个 · {formatBytes(group.bytes)}</small></div>
        <CodePath value={group.destination} />
      </li>
    ))}
  </ul>;
}

/** Name the actual media present without synthesizing a filename or destination. */
function unitMediaLabel(row: MediaBatchPreviewUnit) {
  if (row.recycle_reason) return recycleLabels[row.recycle_reason];
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
function UnitInspection({ row, onDetails, onClose, closeDisabled }: {
  row: MediaBatchPreviewUnit;
  onDetails: OpenUnitDetails;
  onClose?: () => void;
  closeDisabled: boolean;
}) {
  const samples = row.sample_moves?.filter(move => move.source !== move.target).slice(0, 3) ?? [];
  const paths = usePathPrefix(commonDirectoryPrefix(samples.flatMap(move => [move.source, move.target])));
  const archiveLift = row.operation === 'promote_repeated_archive_children';
  const hasFacts = row.status === 'ready' && !row.recycle_reason && samples.length > 0;
  const mappingAction = row.mapping_id && (
    <ConsoleButton size="sm" variant="ghost" onClick={event => onDetails(row, event.currentTarget)}>
      查看完整映射（{row.total_proposals.toLocaleString()}）
    </ConsoleButton>
  );
  return (
    <section className="nfc-unit-inspection" aria-label="所选目录整理详情" id="organizer-unit-inspection">
      <header className="nfc-organizer-inspection-header">
        <div>
          <h3 title={row.unit}>{unitName(row.unit)}</h3>
          <p>
            <span>{unitMediaLabel(row)}</span>
            {row.recycle_reason ? <span>移入极空间回收站</span> : archiveLift
              ? <span>保留子目录内部结构</span>
              : row.total_bytes !== undefined && <span>{formatBytes(row.total_bytes)}</span>}
          </p>
        </div>
        <div className="nfc-organizer-inspection-actions">
          <StatusBadge status={previewTones[row.status]} label={row.recycle_reason ? '待回收' : previewLabels[row.status]} />
          {onClose && <button className="nfc-file-workspace-icon" type="button" aria-label="关闭整理详情"
            onClick={onClose} disabled={closeDisabled}>
            <ConsoleIcon name="x" size={16} />
          </button>}
        </div>
      </header>
      <OrganizerStructure unit={row} />
      {samples.length > 0 && <section className="nfc-organizer-path-samples">
        <div className="nfc-organizer-path-samples-heading">
          <h4>{archiveLift ? '目录上提示例' : '路径变化示例'}</h4>
          {mappingAction}
        </div>
        <div className="nfc-organizer-sample-list">
          <PathPrefixDisclosure {...paths} compact />
          <ul aria-label="源路径与目标路径">
            {samples.map(sample => (
              <li className="nfc-organizer-sample-row" key={sample.source}>
                <CodePath value={sample.source} displayValue={paths.displayPath(sample.source)} />
                <ConsoleIcon className="nfc-organizer-sample-arrow" name="arrow-right" size={13} />
                <CodePath value={sample.target} displayValue={paths.displayPath(sample.target)} />
              </li>
            ))}
          </ul>
        </div>
      </section>}
      {samples.length === 0 && mappingAction}
      {hasFacts ? (
        <details className="nfc-organizer-unit-facts">
          <summary>更多整理信息</summary>
          <CodePath value={row.unit} />
          <div className="nfc-unit-facts">
            <span>移动 {row.needed_moves.toLocaleString()} · 改名 {row.renamed_count.toLocaleString()}</span>
            {row.wrapper_cleanup_count !== undefined && <span>清空旧分类 {row.wrapper_cleanup_count}</span>}
          </div>
          {row.total_proposals > (row.sample_moves?.length ?? 0) &&
            <p className="nfc-organizer-structure-note">目录结构根据预览示例和目标分类展示。</p>}
          {row.groups.length > 0 && <>
            <h4>全部目标分类（{row.groups.length.toLocaleString()}）</h4>
            <OrganizerDestinations groups={row.groups} />
          </>}
        </details>
      ) : <div className="nfc-organizer-unit-path"><CodePath value={row.unit} /></div>}
      <PreviewUnitDetails row={row} onDetails={onDetails} groupsShown={hasFacts} />
    </section>
  );
}

/** Display a preview's aggregated totals and the current page of independent units. */
export function MediaOrganizerPreviewReport({ preview, selected, onSelect, onDetails, action, children, footer,
  detail, onDismissDetails, pending = false, detailBusy = false }: {
  preview: MediaBatchPreview;
  selected?: MediaBatchPreviewUnit;
  onSelect: (row: MediaBatchPreviewUnit) => void;
  onDetails: OpenUnitDetails;
  action: React.ReactNode;
  children: React.ReactNode;
  footer: React.ReactNode;
  detail?: React.ReactNode;
  onDismissDetails?: () => void;
  pending?: boolean;
  detailBusy?: boolean;
}) {
  const { showThumbnails } = useDisplayPreferences();
  const { isMobile } = useResponsive();
  const [view, setView] = useState<'grid' | 'list'>('list');
  const [selectionKey, setSelectionKey] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const selectedCard = useRef<HTMLButtonElement>(null);
  const selectedKey = selected ? preview.job_id + '/' + selected.unit : null;
  const listView = !showThumbnails || view === 'list';
  const sheetOpen = isMobile && selectedKey !== null && selectedKey === selectionKey && !collapsed;
  const desktopOpen = !isMobile && selected !== undefined && !collapsed;

  /** Close only the current inspector and clear details tied to its row. */
  function closeInspection() {
    if (detailBusy) return;
    setCollapsed(true);
    onDismissDetails?.();
    if (!isMobile) selectedCard.current?.focus({ preventScroll: true });
  }

  /** Mobile opens a sheet only on explicit selection, including when reopening the same row. */
  function selectUnit(row: MediaBatchPreviewUnit, opener?: HTMLButtonElement) {
    if (detailBusy) return;
    setCollapsed(false);
    if (isMobile) {
      // Safari does not focus a button after touch or mouse activation.
      opener?.focus({ preventScroll: true });
      setSelectionKey(preview.job_id + '/' + row.unit);
    }
    onSelect(row);
  }

  const summary = preview.summary;
  if (!summary) return null;
  const inspector = selected && <>
    <UnitInspection key={selected.unit} row={selected} onDetails={onDetails}
      onClose={isMobile ? undefined : closeInspection} closeDisabled={detailBusy} />
    {detail}
  </>;

  return (
    <section className="nfc-organizer-workspace-report nfc-v2-batch-organizer-report" aria-label="整理预览工作台">
      <div className={'nfc-organizer-workspace-body' + (desktopOpen ? ' has-inspector' : '')}>
        <div className="nfc-organizer-workspace-list">
          <header className="nfc-organizer-preview-header">
            <div className="nfc-organizer-preview-heading">
              <h2>整理预览</h2>
              <details className="nfc-organizer-preview-options">
                <summary aria-label="预览显示与统计" title="预览显示与统计">
                  <ConsoleIcon name="sliders" size={15} />
                </summary>
                <div className="nfc-organizer-preview-options-panel">
                  <div className="nfc-organizer-workspace-view-actions">
                    <div className="nfc-file-workspace-view" role="group" aria-label="整理预览显示方式">
                      <button type="button" aria-label="网格视图" aria-pressed={!listView} disabled={!showThumbnails}
                        onClick={() => setView('grid')}><ConsoleIcon name="layout-dashboard" size={15} /></button>
                      <button type="button" aria-label="列表视图" aria-pressed={listView}
                        onClick={() => setView('list')}><ConsoleIcon name="list-checks" size={15} /></button>
                    </div>
                    <ThumbnailSwitch />
                  </div>
                  <div className="nfc-unit-facts" aria-label="变更统计">
                    <span>{summary.unit_count.toLocaleString()} 个整理单元 · {summary.file_count.toLocaleString()} 个文件</span>
                    {summary.total_bytes !== undefined && <span>{formatBytes(summary.total_bytes)}</span>}
                    <span>待整理 {summary.ready_count - (summary.recycle_count ?? 0)}</span>
                    <span>冲突 {summary.blocked_count}</span>
                    {!!summary.recycle_count && <span>待回收 {summary.recycle_count}</span>}
                    <span>已整理 {summary.already_organized_count}</span>
                    <span>跳过 {summary.skipped_count}</span>
                    {!!summary.needs_assignment_count && <span>待归属作者 {summary.needs_assignment_count}</span>}
                    {summary.totals && <span>图片 {summary.totals.P} · 视频 {summary.totals.V} · 其他 {summary.totals.Other}</span>}
                    <span>预计移动 {summary.needed_moves.toLocaleString()}</span>
                    <span>预计改名 {summary.renamed_count.toLocaleString()}</span>
                    {summary.wrapper_cleanup_count !== undefined && <span>预计清空旧分类 {summary.wrapper_cleanup_count}</span>}
                  </div>
                </div>
              </details>
            </div>
            {children}
          </header>
          {pending ? <p className="nfc-file-workspace-loading" role="status">正在读取此页预览…</p> : preview.units.length > 0 ? (
          <ul className={'nfc-unit-gallery' + (listView ? ' is-compact' : '')} role="list" aria-label="逐目录整理预览">
            {preview.units.map(row => {
              const sample = row.sample_moves?.find(move => move.kind === 'P') ??
                row.sample_moves?.find(move => move.kind === 'V');
              return (
                <li key={preview.job_id + '/' + row.unit}>
                  <button type="button" className="nfc-unit-card" aria-pressed={selected?.unit === row.unit}
                    disabled={detailBusy}
                    ref={selected?.unit === row.unit ? selectedCard : undefined}
                    title={row.unit} aria-haspopup={isMobile ? 'dialog' : undefined}
                    aria-controls={selected?.unit === row.unit && (desktopOpen || sheetOpen) ? 'organizer-unit-inspection' : undefined}
                    onClick={event => selectUnit(row, event?.currentTarget)}>
                    <MediaThumbnail path={row.unit} kind={row.recycle_reason ? 'file' : 'directory'}
                      size={listView ? 'small' : 'cover'} representativeFile={sample?.source} />
                    <span className="nfc-unit-caption">
                      <strong>{unitName(row.unit)}</strong>
                      <small>{row.status === 'blocked'
                        ? conflictLabels[row.conflicts[0]?.reason] ?? row.reason ?? '需要核对目标路径'
                        : unitMediaLabel(row)}</small>
                      <StatusBadge status={previewTones[row.status]} label={row.recycle_reason ? '待回收' : previewLabels[row.status]} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          ) : <ConsoleEmpty title="当前筛选没有整理单元" />}
          {footer && <div className="nfc-organizer-preview-pagination">{footer}</div>}
        </div>
        {desktopOpen && <aside key={selectedKey} className="nfc-organizer-workspace-inspector" aria-label="整理详情">{inspector}</aside>}
      </div>
      {isMobile && selectionKey !== null && <ConsoleSheet open={sheetOpen} onClose={closeInspection} title="整理详情"
        className="nfc-organizer-workspace-sheet" dismissDisabled={detailBusy}>
        {inspector}
      </ConsoleSheet>}
      {action && <footer className="nfc-unit-confirmation">
        <span><strong>{summary.recycle_count === summary.ready_count
          ? `${summary.recycle_count.toLocaleString()} 个附带文件移入极空间回收站`
          : `${(summary.ready_count - (summary.recycle_count ?? 0)).toLocaleString()} 个目录可整理`}</strong>
          {!!summary.recycle_count && summary.recycle_count !== summary.ready_count &&
            ` · ${summary.recycle_count.toLocaleString()} 个附带文件移入极空间回收站`}
          {summary.blocked_count > 0 && ` · ${summary.blocked_count} 处冲突`}
          {summary.already_organized_count > 0 && ` · ${summary.already_organized_count} 项已整理`}</span>
        {action}
      </footer>}
    </section>
  );
}

/** Read the selected unit's mapping independently of the preview table page. */
export function MediaOrganizerMappingReport({ previewId, mappingId, unit, onClose, embedded = false }: {
  previewId: OrganizerJobId;
  mappingId: string;
  unit: string;
  onClose: () => void;
  embedded?: boolean;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const reportRef = useRef<HTMLDivElement>(null);
  const { data, error, isError } = useQuery({
    queryKey: ['mediaOrganizerMapping', previewId, mappingId, page, pageSize],
    queryFn: () => mediaOrganizerBatchApi.getMapping(previewId, mappingId, page, pageSize),
  });
  const paths = usePathPrefix(commonDirectoryPrefix(data?.moves.flatMap(move => [move.source, move.target]) ?? []));
  const records = data && <ul className="nfc-v2-batch-organizer-records" role="list" aria-label="媒体文件位置调整明细">
    {data.moves.map(move => (
      <li key={move.source}>
        <div className="nfc-v2-batch-organizer-record-heading">
          <strong className="nfc-v2-batch-organizer-kind">{mappingKindLabels[move.kind]}</strong>
          {move.kind !== 'Directory' && <span>{formatBytes(move.bytes)}</span>}
        </div>
        <dl className="nfc-v2-batch-organizer-paths">
          <div><dt>源路径</dt><dd><CodePath value={move.source} displayValue={paths.displayPath(move.source)} /></dd></div>
          <div><dt>目标路径</dt><dd><CodePath value={move.target} displayValue={paths.displayPath(move.target)} /></dd></div>
        </dl>
      </li>
    ))}
  </ul>;

  useEffect(() => {
    reportRef.current?.focus({ preventScroll: true });
    reportRef.current?.scrollIntoView?.({ block: embedded ? 'nearest' : 'start', behavior: 'instant' });
  }, [embedded]);

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
            <PathPrefixDisclosure {...paths} />
            <ResponsiveDataView
              desktop={embedded ? records : <div className="nfc-v2-batch-media-scroll">
                <table className="nfc-v2-batch-media-table">
                  <caption className="nfc-v2-batch-media-sr-only">媒体文件位置调整明细</caption>
                  <thead><tr><th scope="col">类型</th><th scope="col">源路径</th>
                    <th scope="col">目标路径</th><th scope="col">大小</th></tr></thead>
                  <tbody>{data.moves.map(move => (
                    <tr key={move.source}>
                      <td>{move.kind === 'Directory' ? mappingKindLabels.Directory : move.kind}</td>
                      <td><CodePath value={move.source} displayValue={paths.displayPath(move.source)} /></td>
                      <td><CodePath value={move.target} displayValue={paths.displayPath(move.target)} /></td>
                      <td>{move.kind === 'Directory' ? '—' : formatBytes(move.bytes)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={records}
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
export function MediaOrganizerResultReport({ report, children, conflictsOnly, onToggleConflicts, pending }: {
  report: MediaBatchResult;
  children: React.ReactNode;
  conflictsOnly: boolean;
  onToggleConflicts: () => void;
  pending: boolean;
}) {
  const cleanupMessage = {
    pending: '报告明细已排队回收，整理结果会保留。',
    released: '报告文件已回收，整理结果已保留。',
    missing: '报告文件已不存在，整理结果已保留。',
  };
  return (
    <DataPanel title="整理结果" variant="dense" className={panelClass}
      action={(report.summary.conflict_count > 0 && !['released', 'missing'].includes(report.report_cleanup_status ?? '')) &&
        <ConsoleButton size="sm" variant="secondary" aria-pressed={conflictsOnly}
          leadingIcon={<ConsoleIcon name={conflictsOnly ? 'list-checks' : 'search'} size={15} />}
          loading={pending}
          onClick={onToggleConflicts}>{conflictsOnly ? '查看全部结果' : '定位冲突'}</ConsoleButton>}>
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
      {pending ? <p className="nfc-file-workspace-loading" role="status">正在读取结果…</p> : report.items.length > 0 ? (
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
      ) : conflictsOnly && !report.report_cleanup_status && <ConsoleEmpty title="没有可查看的冲突结果" />}
      {children}
    </DataPanel>
  );
}
