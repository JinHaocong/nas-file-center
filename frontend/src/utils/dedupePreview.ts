import {
  DedupePreviewMemberRow,
  DirectDedupePreviewResponse,
  FactorContribution,
  MemberDecision,
} from '../types/dedupe';
import { WorkflowPreviewItem } from '../types/workflow';

export function formatScanRootLabel(scanRootIndex?: number, scanRootPath?: string): string {
  if (scanRootIndex === undefined || scanRootIndex === null) return scanRootPath ? scanRootPath.trim() : '-';
  if (scanRootPath && scanRootPath.trim()) return `Scan Root ${scanRootIndex} ${scanRootPath.trim()}`;
  return `Scan Root ${scanRootIndex}`;
}

export function isCanonicalDedupeMetadataComplete(meta: unknown): boolean {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return false;
  const m = meta as Record<string, any>;
  return typeof m.group_provenance_id === 'number' && Number.isInteger(m.group_provenance_id) && typeof m.member_decision === 'string' && m.member_decision.trim().length > 0 && typeof m.group_status === 'string' && typeof m.group_file_size === 'number' && typeof m.scan_root_index === 'number' && typeof m.eligible_as_keep === 'boolean' && typeof m.recommended_keep === 'boolean';
}

export interface DecisionClassification { label: string; color: 'success' | 'error' | 'warning' | 'default'; kind: MemberDecision; }
export function classifyMemberDecision(rawDecision?: string | MemberDecision, eligibleAsKeep?: boolean): DecisionClassification {
  const norm = (rawDecision || '').toUpperCase().replace(/[\s-]+/g, '_');
  if (norm === 'KEEP') return { label: 'KEEP', color: 'success', kind: 'KEEP' };
  if (norm === 'QUARANTINE') return { label: 'QUARANTINE', color: 'error', kind: 'QUARANTINE' };
  if (norm === 'UNAVAILABLE') return { label: 'UNAVAILABLE', color: 'default', kind: 'UNAVAILABLE' };
  if (norm === 'SAFETY_EXCLUDED' || norm === 'SAFETYEXCLUDED' || eligibleAsKeep === false) return { label: 'SAFETY EXCLUDED', color: 'warning', kind: 'SAFETY_EXCLUDED' };
  return { label: 'SKIPPED', color: 'default', kind: 'SKIPPED' };
}
export function mapDirectPreviewRows(response: DirectDedupePreviewResponse): DedupePreviewMemberRow[] { return response?.rows || []; }

export function mapWorkflowPreviewItemsToDedupeRows(items: WorkflowPreviewItem[]): DedupePreviewMemberRow[] {
  if (!items || !Array.isArray(items)) return [];
  return items.map((item) => {
    const meta = item.metadata || {};
    const complete = isCanonicalDedupeMetadataComplete(meta);
    const common = {
      group_provenance_id: typeof meta.group_provenance_id === 'number' ? meta.group_provenance_id : undefined,
      group_status: typeof meta.group_status === 'string' ? meta.group_status : undefined,
      group_skip_reason: meta.group_skip_reason ?? null,
      group_file_size: typeof meta.group_file_size === 'number' ? meta.group_file_size : undefined,
      group_recommended_keep_path: meta.group_recommended_keep_path ?? null,
      group_reclaimable_bytes: typeof meta.group_reclaimable_bytes === 'number' ? meta.group_reclaimable_bytes : undefined,
      group_selection_reason: meta.group_selection_reason ?? null,
      group_balance_info: meta.group_balance_info ?? null,
      absolute_path: meta.absolute_path || item.source_path,
      relative_path: typeof meta.relative_path === 'string' ? meta.relative_path : undefined,
      scan_root_index: typeof meta.scan_root_index === 'number' ? meta.scan_root_index : undefined,
      scan_root_path: typeof meta.scan_root_path === 'string' ? meta.scan_root_path : undefined,
      eligible_as_keep: typeof meta.eligible_as_keep === 'boolean' ? meta.eligible_as_keep : undefined,
      safety_reasons: Array.isArray(meta.safety_reasons) ? meta.safety_reasons : [],
      total_score: typeof meta.total_score === 'number' ? meta.total_score : undefined,
      contributions: Array.isArray(meta.contributions) ? meta.contributions : [],
      is_top_candidate: typeof meta.is_top_candidate === 'boolean' ? meta.is_top_candidate : undefined,
      recommended_keep: typeof meta.recommended_keep === 'boolean' ? meta.recommended_keep : undefined,
      selection_reason: meta.selection_reason || null,
      balance_info: meta.balance_info || null,
      candidate_balance_bucket: typeof meta.candidate_balance_bucket === 'string' ? meta.candidate_balance_bucket : null,
      recursive_last_file_protection_reason: typeof meta.recursive_last_file_protection_reason === 'string' ? meta.recursive_last_file_protection_reason : null,
    };
    if (!complete) return { ...common, member_decision: 'UNAVAILABLE' as const, incomplete: true };
    return {
      ...common,
      group_reclaimable_bytes: common.group_reclaimable_bytes ?? 0,
      relative_path: common.relative_path || '',
      scan_root_path: common.scan_root_path || '',
      is_top_candidate: Boolean(common.is_top_candidate),
      member_decision: meta.member_decision,
      incomplete: false,
    };
  });
}

export interface ReleasedBytesByRootEntry { rootIndex: number; rootPath: string; releasedBytes: number; }
export function mapReleasedBytesByScanRoot(releasedBytes: Record<string, number> | undefined, scanRoots: string[] | undefined): ReleasedBytesByRootEntry[] {
  if (!scanRoots || !Array.isArray(scanRoots)) return [];
  return scanRoots.map((rootPath, idx) => ({ rootIndex: idx, rootPath, releasedBytes: releasedBytes && typeof releasedBytes[String(idx)] === 'number' ? releasedBytes[String(idx)] : 0 }));
}
export function isBalancerContributionExcludedFromFactors(contribution: FactorContribution): boolean {
  if (!contribution || !contribution.factor) return false;
  const f = contribution.factor.toLowerCase();
  return f.includes('balance') || f === 'balanced_by_bytes';
}
