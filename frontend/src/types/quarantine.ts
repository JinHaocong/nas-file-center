export type QuarantineState =
  | 'preparing'
  | 'active'
  | 'restoring'
  | 'purging'
  | 'restored'
  | 'purged'
  | 'inconsistent'
  | 'abandoned'
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
  state: 'purged';
  status: 'purged';
}

export interface QuarantineRetentionPolicy {
  quarantine_retention_days: number;
  updated_at: string | null;
}

export interface QuarantineRetentionPolicyUpdateRequest {
  quarantine_retention_days: number;
}
