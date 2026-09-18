export type QuarantineState =
  | 'preparing'
  | 'active'
  | 'restoring'
  | 'purging'
  | 'restored'
  | 'purged'
  | 'inconsistent'
  | 'abandoned'
  | 'conflict'
  | 'skipped';

export interface QuarantineEntry {
  id: number;
  original_path: string;
  quarantine_path: string;
  task_id: number | null;
  plan_item_id: number | null;
  state: QuarantineState;
  size: number;
  hash: string | null;
  mtime_ns: number;
  device: number;
  inode: number;
  quarantined_at: string | null;
  expires_at: string | null;
  restored_at: string | null;
  purged_at: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface QuarantineListResponse {
  items: QuarantineEntry[];
  total: number;
  page: number;
  page_size: number;
}

export type QuarantineConflictPolicy = 'skip' | 'rename' | 'manual';

export interface QuarantineRestoreRequest {
  conflict_policy?: QuarantineConflictPolicy;
  conflict_strategy?: QuarantineConflictPolicy;
  custom_target?: string;
}

export interface QuarantineRestoreResponse {
  id: number;
  state: 'restored' | 'skipped';
  status: 'restored' | 'skipped';
  restored_to_path: string | null;
  conflict_policy: string;
  conflict_resolved: boolean;
  reason?: string;
}

export interface QuarantinePurgeRequest {
  confirmation: 'DELETE';
}

export interface QuarantinePurgeResponse {
  id: number;
  entry_id?: number;
  state: 'purged';
  status: 'purged';
  purged?: boolean;
  purge_semantics?: 'unlink_v1' | string;
  removed_count?: number;
  removed_roles?: string[];
  recovered_missing_roles?: string[];
  survivor_scope?: string;
  survivor_status?: string;
  hardlink_survivor_count?: number;
  hardlink_survivor_paths?: string[];
  same_content_scope?: string;
  same_content_status?: string;
  independent_copy_count?: number;
  independent_copy_paths?: string[];
  advisory_diagnostics?: string[];
}

export type QuarantineBulkAction = 'restore' | 'purge';
export type QuarantineBulkConflictPolicy = 'skip' | 'rename';

export interface QuarantineBulkPreviewRequest {
  action: QuarantineBulkAction;
  entry_ids: number[];
  conflict_policy?: QuarantineBulkConflictPolicy;
}

export interface QuarantineBulkPlanRequest extends QuarantineBulkPreviewRequest {
  expected_preview_digest: string;
  confirmation?: 'DELETE';
}

export interface QuarantineBulkPreviewItem {
  entry_id: number;
  eligible: boolean;
  reason?: string | null;
  state?: string;
  tx_phase?: string;
  conflict_policy?: QuarantineBulkConflictPolicy;
  target_path?: string;
  purge_topology_manifest?: Record<string, unknown>;
  purge_semantics?: 'unlink_v1' | string;
  mutation_blockers?: string[];
  survivor_scope?: string;
  survivor_status?: string;
  hardlink_survivor_count?: number;
  hardlink_survivor_paths?: string[];
  same_content_scope?: string;
  same_content_status?: string;
  independent_copy_count?: number;
  independent_copy_paths?: string[];
  advisory_diagnostics?: string[];
}

export interface QuarantineBulkPreviewResponse {
  action: QuarantineBulkAction;
  entry_ids: number[];
  eligible_count: number;
  blocked_count: number;
  items: QuarantineBulkPreviewItem[];
  preview_digest: string;
}

export interface QuarantineBulkPlanResponse {
  id: number;
  kind: 'quarantine-bulk-restore' | 'quarantine-bulk-purge';
  status: 'draft';
  expected_changes: number;
  preview_digest: string;
}

export interface QuarantineRetentionPolicy {
  quarantine_retention_days: number;
  updated_at: string | null;
}

export interface QuarantineRetentionPolicyUpdateRequest {
  quarantine_retention_days: number;
}
