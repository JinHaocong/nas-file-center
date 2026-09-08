import {
  DedupePreviewMemberRow,
  DirectDedupePreviewResponse,
  FactorContribution,
  MemberDecision,
} from '../types/dedupe';
import { WorkflowPreviewItem } from '../types/workflow';

export function formatScanRootLabel(scanRootIndex: number, scanRootPath?: string): string {
  if (scanRootPath && scanRootPath.trim()) {
    return `Scan Root ${scanRootIndex} ${scanRootPath.trim()}`;
  }
  return `Scan Root ${scanRootIndex}`;
}

export interface DecisionClassification {
  label: string;
  color: 'success' | 'error' | 'warning' | 'default';
  kind: MemberDecision;
}

export function classifyMemberDecision(rawDecision: string | MemberDecision): DecisionClassification {
  const norm = (rawDecision || '').toUpperCase().replace(/[\s-]+/g, '_');
  if (norm === 'KEEP') {
    return { label: 'KEEP', color: 'success', kind: 'KEEP' };
  }
  if (norm === 'QUARANTINE') {
    return { label: 'QUARANTINE', color: 'error', kind: 'QUARANTINE' };
  }
  if (norm === 'SAFETY_EXCLUDED' || norm === 'SAFETYEXCLUDED') {
    return { label: 'SAFETY EXCLUDED', color: 'warning', kind: 'SAFETY_EXCLUDED' };
  }
  return { label: 'SKIPPED', color: 'default', kind: 'SKIPPED' };
}

export function mapDirectPreviewRows(response: DirectDedupePreviewResponse): DedupePreviewMemberRow[] {
  return response?.rows || [];
}

export function mapWorkflowPreviewItemsToDedupeRows(items: WorkflowPreviewItem[]): DedupePreviewMemberRow[] {
  if (!items || !Array.isArray(items)) return [];
  return items.map((item) => {
    const meta = item.metadata || {};
    return {
      group_provenance_id: meta.group_provenance_id || 0,
      group_status: meta.group_status || 'actionable',
      group_skip_reason: meta.group_skip_reason || null,
      group_file_size: meta.group_file_size || 0,
      group_recommended_keep_path: meta.group_recommended_keep_path || null,
      group_reclaimable_bytes: meta.group_reclaimable_bytes || 0,
      group_selection_reason: meta.group_selection_reason || null,
      group_balance_info: meta.group_balance_info || null,
      absolute_path: meta.absolute_path || item.source_path,
      relative_path: meta.relative_path || '',
      scan_root_index: typeof meta.scan_root_index === 'number' ? meta.scan_root_index : 0,
      scan_root_path: meta.scan_root_path || '',
      eligible_as_keep: Boolean(meta.eligible_as_keep),
      safety_reasons: Array.isArray(meta.safety_reasons) ? meta.safety_reasons : [],
      total_score: typeof meta.total_score === 'number' ? meta.total_score : 0,
      contributions: Array.isArray(meta.contributions) ? meta.contributions : [],
      is_top_candidate: Boolean(meta.is_top_candidate),
      recommended_keep: Boolean(meta.recommended_keep),
      member_decision: meta.member_decision || (item.operation === 'keep' ? 'KEEP' : 'QUARANTINE'),
      selection_reason: meta.selection_reason || null,
      balance_info: meta.balance_info || null,
    };
  });
}

export interface ReleasedBytesByRootEntry {
  rootIndex: number;
  rootPath: string;
  releasedBytes: number;
}

export function mapReleasedBytesByScanRoot(
  releasedBytes: Record<string, number> | undefined,
  scanRoots: string[] | undefined
): ReleasedBytesByRootEntry[] {
  if (!scanRoots || !Array.isArray(scanRoots)) return [];
  return scanRoots.map((rootPath, idx) => {
    const key = String(idx);
    const bytes = (releasedBytes && typeof releasedBytes[key] === 'number') ? releasedBytes[key] : 0;
    return {
      rootIndex: idx,
      rootPath,
      releasedBytes: bytes,
    };
  });
}

export function isBalancerContributionExcludedFromFactors(contribution: FactorContribution): boolean {
  if (!contribution || !contribution.factor) return false;
  const f = contribution.factor.toLowerCase();
  return f.includes('balance') || f === 'balanced_by_bytes';
}
