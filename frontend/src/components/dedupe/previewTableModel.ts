import type { DedupePreviewMemberRow } from '../../types/dedupe';
import { classifyMemberDecision } from '../../utils/dedupePreview';

export interface DedupePreviewFilters {
  searchText: string;
  decisionFilter: string;
  rootFilter: number | 'ALL';
}

/** Client filters apply only to the page returned by the authoritative server preview. */
export function filterDedupePreviewRows(rows: DedupePreviewMemberRow[], filters: DedupePreviewFilters) {
  const search = filters.searchText.trim().toLowerCase();
  return rows.filter(row => {
    if (search &&
        !row.absolute_path?.toLowerCase().includes(search) &&
        !row.relative_path?.toLowerCase().includes(search)) return false;
    if (filters.decisionFilter !== 'ALL' &&
        classifyMemberDecision(row.member_decision, row.eligible_as_keep).kind !== filters.decisionFilter) return false;
    if (filters.rootFilter !== 'ALL' && row.scan_root_index !== filters.rootFilter) return false;
    return true;
  });
}

export const decisionFilterOptions = [
  { value: 'ALL', label: '全部决策' },
  { value: 'KEEP', label: '保留 (KEEP)' },
  { value: 'QUARANTINE', label: '隔离 (QUARANTINE)' },
  { value: 'HARDLINK', label: 'Hardlink 优化' },
  { value: 'REFLINK', label: 'Reflink 优化' },
  { value: 'SAFETY_EXCLUDED', label: '安全排除' },
  { value: 'SKIPPED', label: '已跳过 (SKIPPED)' },
  { value: 'UNAVAILABLE', label: '数据不可用 (UNAVAILABLE)' },
] as const;
