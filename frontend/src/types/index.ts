export interface User {
  id: number;
  username: string;
  role: string;
}

export interface SessionInfo {
  id: number;
  ip_address: string;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  is_current: boolean;
}

export interface SystemSettings {
  allow_mutation: boolean;
  allow_delete: boolean;
  protect_last_file: boolean;
  allowed_roots: string[];
  quarantine_root: string;
  fclones_binary: string;
  verification_hash: string;
}

export interface DashboardSummary {
  indexed_files: number;
  indexed_folders: number;
  scan_count: number;
  plan_count: number;
  duplicate_group_count: number;
  queued_or_running_jobs: number;
  latest_reclaimable_bytes: number;
  latest_scan_id?: number | null;
  latest_scan_name?: string | null;
  latest_scan_finished_at?: string | null;
}

export interface IndexRoot {
  id: number;
  root: string;
  files: number;
  folders: number;
  created_at: string;
  last_indexed_at: string | null;
  last_seen_at?: string | null;
  exists: boolean;
  path_state: 'available' | 'missing' | 'blocked';
  has_active_job: boolean;
  active_job_id: number | null;
  active_job_status: string | null;
  can_remove: boolean;
}

export interface ScanJob {
  id: number;
  name: string;
  mode: string;
  roots: string[];
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  total_groups: number;
  total_files_in_groups: number;
  reclaimable_bytes: number;
  has_dependent_plan?: boolean;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface DuplicateFile {
  id: number;
  root_id: number;
  path: string;
  relative_path: string;
  top_level_dir: string;
  size: number;
  mtime_ns: number;
}

export interface DuplicateGroup {
  id: number;
  content_hash: string;
  file_size: number;
  member_count: number;
  reclaimable_bytes: number;
  members: DuplicateFile[];
}

export interface PlanItem {
  id: number;
  sequence: number;
  operation: string;
  source: string;
  target?: string | null;
  keep?: string | null;
  expected_size: number;
  expected_hash?: string | null;
  state: 'planned' | 'validated' | 'executed' | 'completed' | 'failed' | 'skipped';
  reason?: string | null;
}

export type PlanStatus =
  | 'draft'
  | 'frozen'
  | 'validating'
  | 'ready'
  | 'executing'
  | 'completed'
  | 'partial'
  | 'failed';

export type PlanHistoryStatus = 'completed' | 'failed';

export interface DeletePlanResponse {
  deleted: boolean;
  id: number;
}

export interface ClearPlanHistoryResponse {
  deleted_count: number;
}

export interface LegacyPlanSummary {
  plan_count: number;
  item_count: number;
  affected_scan_count: number;
}

export interface ClearLegacyPlansResponse {
  deleted_count: number;
  deleted_item_count: number;
  affected_scan_count: number;
}

export interface Plan {
  id: number;
  name: string;
  kind: string;
  status: PlanStatus;
  expected_changes: number;
  expected_reclaim_bytes: number;
  metadata?: Record<string, any>;
  created_at: string;
  frozen_at?: string | null;
  total_items?: number;
  page?: number;
  page_size?: number;
  items?: PlanItem[];
  active_work_job_id?: number | null;
}

export interface WorkJob {
  id: number;
  kind: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'paused' | 'cancel_requested' | 'cancelled';
  progress_current: number;
  progress_total: number;
  state: Record<string, any>;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface AuditEvent {
  id: number;
  timestamp: string;
  operation: string;
  path: string | null;
  result: string;
  details: Record<string, any>;
}

export interface DataLifecyclePolicy {
  audit_retention_days: number;
  updated_at: string | null;
}

export interface AuditRetentionPreview {
  retention_days: number;
  enabled: boolean;
  cutoff: string | null;
  total_count: number;
  delete_count: number;
  keep_count: number;
  oldest_timestamp: string | null;
  newest_timestamp: string | null;
}

export interface AuditRetentionApplyResult {
  retention_days: number;
  cutoff: string;
  deleted_count: number;
  remaining_count: number;
  self_audit_event_id: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface RenameProposal {
  source: string;
  target: string;
  conflict: boolean;
  conflict_reason?: string | null;
}

export interface OrganizerProposal {
  source: string;
  target: string;
  images: number;
  videos: number;
  total_bytes: number;
  has_suspicious_tag: boolean;
  changed: boolean;
}

export interface DirectoryItem {
  name: string;
  path: string;
  type: 'directory' | 'file' | 'symlink';
  size?: number | null;
  mtime_ns?: number;
}

export interface DirectoryListResponse {
  path: string;
  parent?: string | null;
  items: DirectoryItem[];
  page: number;
  page_size: number;
  total: number;
  has_more: boolean;
  allowed_roots: string[];
}

export interface FavoritePath {
  id: number;
  path: string;
  label?: string | null;
  position: number;
  exists: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecentPath {
  id: number;
  path: string;
  last_used_at: string;
  exists: boolean;
}

export interface OrganizerProfile {
  id: number;
  user_id: number | null;
  slug: string | null;
  builtin_version: number | null;
  name: string;
  description: string | null;
  root: string | null;
  recursive: boolean;
  image_extensions: string[];
  video_extensions: string[];
  rename_template: string;
  statistics_template: string;
  preserve_tags: string[];
  cleanup_patterns: string[];
  numbering_mode: 'none' | 'sequential';
  numbering_start: number;
  numbering_padding: number;
  mtime_mode: 'none' | 'ordered';
  mtime_delay_seconds: number;
  is_builtin: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface OrganizerProposal {
  source: string;
  target: string;
  images: number;
  videos: number;
  files: number;
  folders: number;
  total_bytes: number;
  preserved_tags: string[];
  has_suspicious_tag: boolean;
  changed: boolean;
  conflict: boolean;
  conflict_reason: string | null;
  expected_mtime_order: number | null;
}

export interface OrganizerPreviewSummary {
  total_directories: number;
  changed_directories: number;
  conflicts: number;
  total_bytes: number;
}

export interface OrganizerPreviewResponse {
  snapshot_id?: string;
  profile_id: number;
  profile_name: string;
  root: string;
  summary: OrganizerPreviewSummary;
  proposals: OrganizerProposal[];
  page: number;
  page_size: number;
  total: number;
}

export interface OrganizerProfileListResponse {
  items: OrganizerProfile[];
  total: number;
  page: number;
  page_size: number;
}

export * from './task';
