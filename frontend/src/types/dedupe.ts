export type DedupeSelectionMode = 'weighted' | 'balanced_by_bytes';

export type DedupeMtimeMode = 'none' | 'newest' | 'oldest';

export type PathPriorityScope = 'absolute' | 'relative';

export interface PathPriorityRule {
  scope: PathPriorityScope;
  pattern: string;
}

export interface PathPriorityFactorConfig {
  enabled: boolean;
  weight: number;
  rules: PathPriorityRule[];
}

export interface PreferredExtensionFactorConfig {
  enabled: boolean;
  weight: number;
  extensions: string[];
}

export interface MtimeFactorConfig {
  mode: DedupeMtimeMode;
  weight: number;
}

export interface DedupeFactorsConfig {
  path_priority: PathPriorityFactorConfig;
  preferred_extension: PreferredExtensionFactorConfig;
  mtime: MtimeFactorConfig;
}

export interface DedupeScorerConfig {
  schema_version: 1;
  selection_mode: DedupeSelectionMode;
  factors: DedupeFactorsConfig;
}

export interface DirectAdvancedDedupeGenerateRequest {
  scorer_config: DedupeScorerConfig;
  expected_preview_digest: string;
}

export interface DirectAdvancedDedupeGenerateResponse {
  id: number;
  plan_id: number;
  status: string;
  items: number;
  expected_changes: number;
  expected_reclaim_bytes: number;
  preview_digest: string;
}

export interface DirectDedupePreviewRequest {
  page?: number;
  page_size?: number;
  scorer_config?: DedupeScorerConfig;
}

export interface FactorContribution {
  factor: string;
  configured_weight: number;
  actual_contribution: number;
  reason?: string;
}

export interface BalanceInfo {
  spread_before?: number;
  spread_after?: number;
  released_bytes_by_scan_root?: Record<string, number>;
  [key: string]: any;
}

export type MemberDecision = 'KEEP' | 'QUARANTINE' | 'SAFETY_EXCLUDED' | 'SKIPPED' | 'UNAVAILABLE';

export interface DedupePreviewMemberRow {
  group_provenance_id?: number;
  group_status?: 'actionable' | 'skipped' | string;
  group_skip_reason?: string | null;
  group_file_size?: number;
  group_recommended_keep_path?: string | null;
  group_reclaimable_bytes?: number;
  group_selection_reason?: string | null;
  group_balance_info?: BalanceInfo | null;
  absolute_path: string;
  relative_path?: string;
  scan_root_index?: number;
  scan_root_path?: string;
  eligible_as_keep?: boolean;
  safety_reasons?: string[];
  total_score?: number;
  contributions?: FactorContribution[];
  is_top_candidate?: boolean;
  recommended_keep?: boolean;
  member_decision?: MemberDecision;
  selection_reason?: string | null;
  balance_info?: BalanceInfo | null;
  incomplete?: boolean;
}

export interface DedupeSummary {
  scan_job_id?: number;
  scan_roots?: string[];
  dedupe_engine_version?: number;
  selection_mode?: DedupeSelectionMode;
  group_count: number;
  candidate_member_count: number;
  actionable_group_count: number;
  skipped_group_count: number;
  planned_quarantine_count: number;
  expected_reclaim_bytes: number;
  released_bytes_by_scan_root?: Record<string, number>;
  scorer_config_digest?: string;
  source_snapshot_digest?: string;
  decision_digest?: string;
  preview_digest?: string;
  effective_safety_policy?: {
    protect_last_file?: boolean;
    allowed_roots?: string[];
    quarantine_root?: string | null;
    [key: string]: any;
  };
}

export interface DirectDedupePreviewResponse {
  scan_job_id: number;
  scan_roots: string[];
  selection_mode: DedupeSelectionMode;
  page: number;
  page_size: number;
  total_pages: number;
  total_rows: number;
  rows: DedupePreviewMemberRow[];
  summary: DedupeSummary;
  preview_digest: string;
  scorer_config_digest: string;
  source_snapshot_digest: string;
  decision_digest: string;
  dedupe_engine_version: number;
  preview_source: string;
  live_filesystem_verified: boolean;
  group_count: number;
  candidate_member_count: number;
  actionable_group_count: number;
  skipped_group_count: number;
  planned_quarantine_count: number;
  expected_reclaim_bytes: number;
  released_bytes_by_scan_root: Record<string, number>;
  effective_safety_policy: {
    protect_last_file?: boolean;
    allowed_roots?: string[];
    quarantine_root?: string | null;
  };
}
