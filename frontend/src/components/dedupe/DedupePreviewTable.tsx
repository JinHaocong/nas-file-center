import React, { useMemo, useState } from 'react';
import type { DedupePreviewMemberRow } from '../../types/dedupe';
import { formatScanRootLabel, classifyMemberDecision } from '../../utils/dedupePreview';
import {
  getEligibilityPresentation, formatOptionalGroupId, formatOptionalFileSize,
} from '../../utils/dedupePresentation';
import { ActionBar } from '../ui/ActionBar';
import { ResponsiveDataView } from '../ui/ResponsiveDataView';
import { CodePath } from '../ui/CodePath';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsolePagination } from '../ui/ConsolePagination';
import { filterDedupePreviewRows, decisionFilterOptions } from './previewTableModel';

interface Props {
  rows: DedupePreviewMemberRow[];
  loading?: boolean;
  onSelectMember?: (row: DedupePreviewMemberRow) => void;
  pagination?: {
    current: number;
    pageSize: number;
    total: number;
    onChange: (page: number, pageSize: number) => void;
  } | false;
  scanRoots?: string[];
}

export const DedupePreviewTable: React.FC<Props> = ({
  rows, loading = false, onSelectMember, pagination, scanRoots,
}) => {
  const [searchText, setSearchText] = useState('');
  const [decisionFilter, setDecisionFilter] = useState<string>('ALL');
  const [rootFilter, setRootFilter] = useState<number | 'ALL'>('ALL');
  const [localPage, setLocalPage] = useState(1);
  const [localPageSize, setLocalPageSize] = useState(20);
  const filteredRows = useMemo(
    () => filterDedupePreviewRows(rows, { searchText, decisionFilter, rootFilter }),
    [rows, searchText, decisionFilter, rootFilter],
  );
  const isServerPaged = Boolean(pagination);
  const visibleRows = isServerPaged || pagination === false
    ? filteredRows
    : filteredRows.slice((localPage - 1) * localPageSize, localPage * localPageSize);
  const paginationView = pagination ? (
    <ConsolePagination page={pagination.current} pageSize={pagination.pageSize}
      total={pagination.total} pageSizes={[20, 50, 100]}
      onChange={pagination.onChange} />
  ) : pagination === false ? null : (
    <ConsolePagination page={localPage} pageSize={localPageSize} total={filteredRows.length}
      pageSizes={[10, 20, 50, 100]}
      onChange={(page, size) => { setLocalPage(page); setLocalPageSize(size); }} />
  );
  const updateFilter = (apply: () => void) => {
    apply();
    setLocalPage(1);
  };

  const DecisionBadge = ({ row }: { row: DedupePreviewMemberRow }) => {
    const decision = classifyMemberDecision(row.member_decision, row.eligible_as_keep);
    return (
      <span className={'nfc-operation-badge nfc-decision-' + decision.kind.toLowerCase().replace(/_/g, '-')}>
        {decision.label}
      </span>
    );
  };

  const filters = (
    <ActionBar className="nfc-filter-bar nfc-dedupe-preview-filters nfc-v2-dedupe-preview-filters">
      <label className="nfc-v2-dedupe-filter-search">
        <span className="nfc-v2-sr-only">按路径搜索</span>
        <ConsoleIcon name="search" size={16} />
        <input type="search" placeholder="按绝对路径或相对路径过滤..."
          value={searchText} onChange={event => updateFilter(() => setSearchText(event.target.value))} />
      </label>
      <label className="nfc-v2-dedupe-filter-select">
        <span className="nfc-v2-sr-only">按决策筛选</span>
        <select aria-label="决策筛选" value={decisionFilter}
          onChange={event => updateFilter(() => setDecisionFilter(event.target.value))}>
          {decisionFilterOptions.map(option =>
            <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      {scanRoots && scanRoots.length > 0 && (
        <label className="nfc-v2-dedupe-filter-select">
          <span className="nfc-v2-sr-only">按扫描根目录筛选</span>
          <select aria-label="扫描根目录筛选" value={rootFilter}
            onChange={event => updateFilter(() =>
              setRootFilter(event.target.value === 'ALL' ? 'ALL' : Number(event.target.value)))}>
            <option value="ALL">全部扫描根</option>
            {scanRoots.map((root, idx) =>
              <option key={idx} value={idx}>{formatScanRootLabel(idx, root)}</option>)}
          </select>
        </label>
      )}
      <span className="nfc-panel-count" aria-live="polite">
        本页符合条件 {filteredRows.length} / {rows.length} 个成员
        {pagination ? ' · 服务器总计 ' + pagination.total : ''}
      </span>
    </ActionBar>
  );

  const explain = (row: DedupePreviewMemberRow) => (
    <ConsoleButton variant="ghost" size="sm" disabled={!onSelectMember || loading}
      leadingIcon={<ConsoleIcon name="file-search" size={15} />}
      onClick={() => onSelectMember?.(row)}>解释决策</ConsoleButton>
  );
  const reason = (row: DedupePreviewMemberRow) =>
    row.storage_blocking_reason || row.selection_reason || row.group_selection_reason || '—';

  return (
    <div className="nfc-dedupe-preview-table nfc-v2-dedupe-preview">
      {filters}
      {loading && <p className="nfc-v2-dedupe-loading" role="status">正在重新计算权威预览…</p>}
      {!loading && filteredRows.length === 0 && (
        <p className="nfc-v2-dedupe-empty" role="status">当前页没有符合筛选条件的成员。</p>
      )}
      <ResponsiveDataView
        desktop={
          <div className="nfc-v2-dedupe-table-scroll">
            <table className="nfc-v2-dedupe-table">
              <thead><tr>
                <th scope="col">决策</th>
                <th scope="col">文件路径</th>
                <th scope="col">扫描根目录</th>
                <th scope="col">评分</th>
                <th scope="col">保留资格</th>
                <th scope="col">决策原因</th>
                <th scope="col">操作</th>
              </tr></thead>
              <tbody>{visibleRows.map((row, index) => {
                const eligibility = getEligibilityPresentation(row.eligible_as_keep);
                return (
                  <tr key={(row.group_provenance_id ?? 'ungrouped') + '_' + row.absolute_path + '_' + index}>
                    <td><div className="nfc-v2-dedupe-badges">
                      <DecisionBadge row={row} />
                      {row.recommended_keep && <span className="nfc-kind-badge">推荐保留</span>}
                    </div></td>
                    <td><div className="nfc-dedupe-path-cell">
                      <CodePath value={row.absolute_path} />
                      <div className="nfc-table-meta">
                        {formatOptionalGroupId(row.group_provenance_id)} · 单文件 {formatOptionalFileSize(row.group_file_size)}
                        {row.relative_path ? ' · 相对 ' + row.relative_path : ''}
                      </div>
                    </div></td>
                    <td><span className="nfc-kind-badge nfc-dedupe-root-badge" title={formatScanRootLabel(row.scan_root_index, row.scan_root_path)}>
                      {formatScanRootLabel(row.scan_root_index, row.scan_root_path)}
                    </span></td>
                    <td className="nfc-mono nfc-v2-dedupe-score">
                      {row.total_score !== undefined ? row.total_score.toLocaleString() : '—'}
                    </td>
                    <td><span className={'nfc-v2-dedupe-eligibility is-' + eligibility.status}
                      title={row.safety_reasons?.join('; ') || eligibility.text}>{eligibility.text}</span></td>
                    <td><span className={row.storage_blocking_reason ? 'nfc-warning-text' : 'nfc-table-meta'}
                      title={reason(row)}>{reason(row)}</span></td>
                    <td>{explain(row)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        }
        mobile={
          <div className="nfc-mobile-record-list">
            {visibleRows.map((row, index) => {
              const decision = classifyMemberDecision(row.member_decision, row.eligible_as_keep);
              const eligibility = getEligibilityPresentation(row.eligible_as_keep);
              return (
                <article className="nfc-dedupe-member-mobile-card"
                  key={(row.group_provenance_id ?? 'ungrouped') + '_' + row.absolute_path + '_' + index}>
                  <div className="nfc-mobile-record-heading">
                    <div><span className={'nfc-operation-badge nfc-decision-' + decision.kind.toLowerCase().replace(/_/g, '-')}>
                      {decision.label}
                    </span>{row.recommended_keep && <span className="nfc-kind-badge">recommended</span>}</div>
                    <span className="nfc-mono nfc-dedupe-score">{row.total_score ?? '—'}</span>
                  </div>
                  <div className="nfc-dedupe-mobile-path"><CodePath value={row.absolute_path} /></div>
                  <div className="nfc-mobile-record-facts">
                    <span>组 <b>{formatOptionalGroupId(row.group_provenance_id)}</b></span>
                    <span>单文件 <b>{formatOptionalFileSize(row.group_file_size)}</b></span>
                    <span>保留资格 <b title={row.safety_reasons?.join('; ')}>{eligibility.text}</b></span>
                    <span>扫描根 <b>{formatScanRootLabel(row.scan_root_index, row.scan_root_path)}</b></span>
                    <span>原因 <b>{reason(row)}</b></span>
                  </div>
                  <div className="nfc-mobile-record-actions">{explain(row)}</div>
                </article>
              );
            })}
          </div>
        }
      />
      {paginationView}
    </div>
  );
};
