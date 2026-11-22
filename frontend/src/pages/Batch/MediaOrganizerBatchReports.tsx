import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { TaskProgress } from '../../components/tasks/TaskProgress';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { DataPanel } from '../../components/ui/DataPanel';
import { StatusBadge } from '../../components/ui/StatusBadge';

import { getStructuredApiError } from '../../api/errors';
import {
  mediaOrganizerBatchApi, type MediaBatchOutcome, type MediaBatchPreview,
  type MediaBatchPreviewUnit, type MediaBatchResult, type OrganizerJobId,
} from '../../api/mediaOrganizerBatch';

import { formatBytes } from '../../utils/format';

const panelClass = 'nfc-v2-batch-media-panel';
const previewLabels = {
  ready: '待整理', blocked: '冲突', skipped: '无需处理', already_organized: '已整理',
};
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

/** Display a preview's aggregated totals and the current page of independent units. */
export function MediaOrganizerPreviewReport({ preview, onMapping, action, children, footer }: {
  preview: MediaBatchPreview;
  onMapping: (row: MediaBatchPreviewUnit) => void;
  action: React.ReactNode;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const summary = preview.summary;
  if (!summary) return null;
  return (
    <DataPanel title="整理预览" variant="dense" className={panelClass} action={action}>
      <div className="nfc-v2-batch-media-stats">
        <span>整理单元 <strong>{summary.unit_count.toLocaleString()}</strong></span>
        <span>待整理 <strong>{summary.ready_count.toLocaleString()}</strong></span>
        <span>已整理 <strong>{summary.already_organized_count.toLocaleString()}</strong></span>
        <span>跳过 <strong>{summary.skipped_count.toLocaleString()}</strong></span>
        <span>冲突 <strong>{summary.blocked_count.toLocaleString()}</strong></span>
        <span>文件 <strong>{summary.file_count.toLocaleString()}</strong></span>
        {summary.totals && (
          <span>图片 <strong>{summary.totals.P.toLocaleString()}</strong> · 视频 <strong>{summary.totals.V.toLocaleString()}</strong> · 其他 <strong>{summary.totals.Other.toLocaleString()}</strong></span>
        )}
        {summary.total_bytes !== undefined && <span>总大小 <strong>{formatBytes(summary.total_bytes)}</strong></span>}
        <span>预计移动 <strong>{summary.needed_moves.toLocaleString()}</strong></span>
        <span>预计改名 <strong>{summary.renamed_count.toLocaleString()}</strong></span>
        {summary.wrapper_cleanup_count !== undefined && (
          <span>预计清空旧分类 <strong>{summary.wrapper_cleanup_count.toLocaleString()}</strong></span>
        )}
      </div>
      {children}
      {preview.units.length > 0 ? (
        <div className="nfc-v2-batch-media-scroll">
          <table className="nfc-v2-batch-media-table">
            <caption className="nfc-v2-batch-media-sr-only">逐目录整理预览</caption>
            <thead>
              <tr><th scope="col">整理单元</th><th scope="col">状态</th><th scope="col">文件</th>
                <th scope="col">预计调整</th><th scope="col">目标与冲突</th></tr>
            </thead>
            <tbody>{preview.units.map(row => (
              <tr key={row.unit}>
                <td><CodePath value={row.unit} /></td>
                <td><StatusBadge status={row.status} label={previewLabels[row.status]} /></td>
                <td>{row.totals.P}P / {row.totals.V}V / {row.totals.Other} Other
                  {row.total_bytes !== undefined && <small>{formatBytes(row.total_bytes)}</small>}
                </td>
                <td>移动 {row.needed_moves.toLocaleString()} · 改名 {row.renamed_count.toLocaleString()}
                  {row.wrapper_cleanup_count !== undefined && <small>清空旧分类 {row.wrapper_cleanup_count}</small>}
                </td>
                <td className="nfc-v2-batch-media-reason">
                  {row.groups.map(group => (
                    <div key={group.destination}><CodePath value={group.name} />
                      <small> · {group.count} 个 · {formatBytes(group.bytes)}</small></div>
                  ))}
                  {row.conflicts.length > 0 ? row.conflicts.map((conflict, index) => {
                    const target = conflict.target ?? conflict.directory;
                    return (
                      <p className="nfc-v2-batch-error" key={index}>
                        {conflictLabels[conflict.reason] ?? conflict.reason}
                        {target && <> · <CodePath value={target} /></>}
                        {conflict.existing?.length ? <> · {conflict.existing.join('、')}</> : null}
                      </p>
                    );
                  }) : row.reason && row.status === 'blocked' && <p>{row.reason}</p>}
                  {row.mapping_id && (
                    <ConsoleButton size="sm" variant="secondary" onClick={() => onMapping(row)}>
                      查看完整映射（{row.total_proposals.toLocaleString()}）
                    </ConsoleButton>
                  )}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <ConsoleEmpty title="当前筛选没有整理单元" />}
      {footer}
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
  const { data, error, isError } = useQuery({
    queryKey: ['mediaOrganizerMapping', previewId, mappingId, page, pageSize],
    queryFn: () => mediaOrganizerBatchApi.getMapping(previewId, mappingId, page, pageSize),
  });
  return (
    <DataPanel title="完整源 → 目标映射" variant="dense" className={panelClass}
      description={<CodePath value={unit} />}
      action={<ConsoleButton size="sm" variant="ghost" onClick={onClose}>关闭</ConsoleButton>}>
      {isError ? (
        <p className="nfc-v2-batch-error" role="alert">{getStructuredApiError(error).message || '无法读取完整映射'}</p>
      ) : data ? (
        <>
          <div className="nfc-v2-batch-media-scroll">
            <table className="nfc-v2-batch-media-table">
              <caption className="nfc-v2-batch-media-sr-only">媒体文件位置调整明细</caption>
              <thead><tr><th scope="col">类型</th><th scope="col">源路径</th>
                <th scope="col">目标路径</th><th scope="col">大小</th></tr></thead>
              <tbody>{data.moves.map(move => (
                <tr key={move.source}>
                  <td>{move.kind}</td><td><CodePath value={move.source} /></td>
                  <td><CodePath value={move.target} /></td><td>{formatBytes(move.bytes)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <ConsolePagination page={page} pageSize={pageSize} total={data.total_moves}
            pageSizes={[25, 50, 100]} onChange={(next, size) => { setPage(next); setPageSize(size); }} />
        </>
      ) : <p role="status">正在读取映射…</p>}
    </DataPanel>
  );
}

/** Display durable progress and the success, skip, conflict and failure counts. */
export function MediaOrganizerResultReport({ report, children }: {
  report: MediaBatchResult;
  children: React.ReactNode;
}) {
  return (
    <DataPanel title="整理结果" variant="dense" className={panelClass}>
      <TaskProgress status={report.status} progress={{ ...report.progress, percent: null }} />
      {report.error && <p className="nfc-v2-batch-error" role="alert">{report.error}</p>}
      <div className="nfc-v2-batch-media-stats" role="status">
        {resultStatuses.map(status => (
          <span key={status}>{outcomes[status].label} <strong>{report.summary[`${status}_count`].toLocaleString()}</strong></span>
        ))}
      </div>
      {report.items.length > 0 && (
        <div className="nfc-v2-batch-media-scroll">
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
        </div>
      )}
      {children}
    </DataPanel>
  );
}
