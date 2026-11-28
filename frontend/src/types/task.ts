export type TaskStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'cancel_requested'
  | 'cancelled'
  | 'failed'
  | 'completed';

export interface TaskCapabilities {
  supports_pause: boolean;
  supports_resume: boolean;
  supports_cancel: boolean;
  supports_retry: boolean;
}

export interface TaskProgress {
  current: number;
  total: number;
  message: string | null;
  percent: number | null;
}

export type TaskId = number | string;

export interface TaskOrganizerResult {
  success_count: number;
  conflict_count: number;
  skipped_count: number;
  failed_count: number;
  conflicts_available: boolean;
}

export interface TaskItem {
  id: TaskId;
  job_type: string;
  status: TaskStatus;
  pause_requested?: boolean;
  organizer_result?: TaskOrganizerResult;
  capabilities: TaskCapabilities;
  progress: TaskProgress;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  error: string | null;
  error_code: string | null;
  retry_of: TaskId | null;
}

export interface TaskDetail extends TaskItem {
  checkpoint: Record<string, unknown>;
  payload: Record<string, unknown>;
}

export type TaskLogLevel = 'debug' | 'info' | 'warning' | 'error';

export interface TaskEvent {
  id: number;
  timestamp: string;
  level: TaskLogLevel;
  event_type: string;
  message: string;
  context: Record<string, unknown>;
}

export type WorkerHealthStatus = 'online' | 'stale' | 'offline';

export interface WorkerStatus {
  status: WorkerHealthStatus;
  worker_id: string | null;
  started_at: string | null;
  heartbeat_at: string | null;
  heartbeat_age_seconds: number | null;
}

export interface PaginatedTasksResponse {
  items: TaskItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface PaginatedTaskEventsResponse {
  items: TaskEvent[];
  page: number;
  page_size: number;
  total: number;
}

export interface RetryTaskResponse {
  job: TaskItem;
  retry_of: number;
}

export type TerminalTaskStatus = 'completed' | 'failed' | 'cancelled';

export interface OrganizerReportCleanupFeedback {
  queued_count: number;
  retained_count: number;
}

export type OrganizerReportStatus = 'retained' | 'reclaimable' | 'orphan' | 'pending' | 'released' | 'unknown';

export interface OrganizerReportItem {
  job_id: string;
  kind: 'preview' | 'execution';
  status: OrganizerReportStatus;
  reason: string;
  bytes: number;
  files: number;
  reclaimed_bytes?: number;
}

export interface OrganizerReportInventoryResponse {
  read_only: true;
  items: OrganizerReportItem[];
  total: number;
  page: number;
  page_size: number;
  pending_count: number;
  total_bytes: number;
  reclaimed_bytes: number;
}

export interface DeleteTaskResponse {
  deleted: boolean;
  id: TaskId;
  report_cleanup?: OrganizerReportCleanupFeedback;
}

export interface ClearTaskHistoryResponse {
  deleted_count: number;
  report_cleanup?: OrganizerReportCleanupFeedback;
}
