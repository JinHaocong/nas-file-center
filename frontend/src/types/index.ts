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
}

export interface IndexRoot {
  root: string;
  files: number;
  folders: number;
  last_seen_at: string | null;
}

export interface ScanJob {
  id: number;
  name: string;
  mode: string;
  roots: string[];
  status: 'queued' | 'running' | 'completed' | 'failed';
  total_groups: number;
  total_files_in_groups: number;
  reclaimable_bytes: number;
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

export interface Plan {
  id: number;
  name: string;
  kind: string;
  status: 'draft' | 'frozen' | 'validating' | 'ready' | 'executing' | 'completed' | 'partial' | 'failed';
  expected_changes: number;
  expected_reclaim_bytes: number;
  metadata?: Record<string, any>;
  created_at: string;
  frozen_at?: string | null;
  total_items?: number;
  page?: number;
  page_size?: number;
  items?: PlanItem[];
}

export interface WorkJob {
  id: number;
  kind: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
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
