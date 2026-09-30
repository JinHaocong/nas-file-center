export type DedupeSelectionMode =
  | 'weighted'
  | 'balanced_by_bytes'
  | 'recursive_directory_balanced_by_bytes';

export type DedupeMtimeMode = 'none' | 'newest' | 'oldest';

export type DedupeStorageAction = 'quarantine' | 'hardlink' | 'reflink';

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
  storage_action?: DedupeStorageAction;
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
  storage_action?: DedupeStorageAction;
}

export interface FactorContribution {
  factor: string;
  configured_weight: number;
  actual_contribution: number;
  reason?: string;
}

export interface BalanceInfo {
  balance_source?: string;
  lca?: string;
  lca_depth?: number;
  anchor_root?: string;
  parent_bucket?: string | null;
  recursive_last_file_protection?: string;
  bucket_released_bytes_before?: Record<string, number>;
  bucket_released_bytes_after?: Record<string, number>;
  spread_before?: number;
  spread_after?: number;
  released_bytes_by_scan_root?: Record<string, number>;
  [key: string]: any;
}

export type MemberDecision =
  | 'KEEP'
  | 'QUARANTINE'
  | 'HARDLINK'
  | 'REFLINK'
  | 'SAFETY_EXCLUDED'
  | 'SKIPPED'
  | 'UNAVAILABLE';

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
  candidate_balance_bucket?: string | null;
  recursive_last_file_protection_reason?: string | null;
  storage_action?: DedupeStorageAction;
  storage_capability?: 'NOT_CHECKED' | 'SUPPORTED' | 'UNSUPPORTED' | 'UNKNOWN' | string | null;
  storage_metadata_compatible?: boolean | null;
  storage_blocking_reason?: string | null;
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
  storage_action?: DedupeStorageAction;
  planned_action_count?: number;
  storage_blocked_count?: number;
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
  storage_action?: DedupeStorageAction;
  planned_action_count?: number;
  storage_blocked_count?: number;
  planned_quarantine_count: number;
  expected_reclaim_bytes: number;
  released_bytes_by_scan_root: Record<string, number>;
  effective_safety_policy: {
    protect_last_file?: boolean;
    allowed_roots?: string[];
    quarantine_root?: string | null;
  };
}


export interface DedupeDiagnosticPath {
  requested_path: string;
  resolved_path: string | null;
  allowed: boolean;
  exists: boolean;
  is_symlink: boolean;
  is_regular_file: boolean;
  in_quarantine: boolean;
  device: number | null;
  inode: number | null;
  size: number | null;
  mtime_ns: number | null;
  sha256: string | null;
  hash_error: string | null;
}

export interface DedupeDiagnosticScanPath {
  resolved_path: string | null;
  scan_root_index: number | null;
  included_in_duplicate_snapshot: boolean;
  memberships: Array<{
    duplicate_file_id: number;
    group_id: number;
    root_id: number;
    snapshot_size: number;
    snapshot_mtime_ns: number;
    snapshot_device: number;
    snapshot_inode: number;
    discovery_hash: string;
  }>;
  reasons: string[];
}

export interface DedupeDiagnosticScanContext {
  scan_job_id: number;
  name: string;
  status: string;
  mode: string;
  roots: string[];
  fclones_args: {
    min_size: string | null;
    name_patterns: string[] | null;
    exclude_patterns: string[] | null;
    match_links: boolean;
    hidden: boolean;
    no_ignore: boolean;
  };
  paths: DedupeDiagnosticScanPath[];
  same_duplicate_group: boolean;
  shared_group_ids: number[];
}

export interface DedupeDiagnosticResponse {
  diagnosis:
    | 'PATH_OUTSIDE_CONFIGURED_ROOTS'
    | 'PATH_NOT_FOUND'
    | 'SYMLINK_UNSUPPORTED'
    | 'NOT_REGULAR_FILE'
    | 'SAME_FILESYSTEM_ENTRY'
    | 'DIFFERENT_SIZE'
    | 'DIFFERENT_CONTENT'
    | 'EXACT_CONTENT_DUPLICATE'
    | 'INDETERMINATE';
  same_filesystem_entry: boolean;
  size_match: boolean | null;
  sha256_match: boolean | null;
  exact_duplicate_copies: boolean;
  paths: [DedupeDiagnosticPath, DedupeDiagnosticPath];
  scan: DedupeDiagnosticScanContext | null;
}
