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

export interface TaskItem {
  id: number;
  job_type: string;
  status: TaskStatus;
  capabilities: TaskCapabilities;
  progress: TaskProgress;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  error: string | null;
  error_code: string | null;
  retry_of: number | null;
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
