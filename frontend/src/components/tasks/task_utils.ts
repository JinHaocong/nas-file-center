import {
  TaskStatus,
  WorkerHealthStatus,
  TaskLogLevel,
  TaskCapabilities,
} from '../../types/task';

export const TASK_STATUS_CONFIG: Record<
  TaskStatus,
  { label: string; color: string }
> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  paused: { label: '已暂停', color: 'warning' },
  cancel_requested: { label: '取消中', color: 'warning' },
  cancelled: { label: '已取消', color: 'default' },
  failed: { label: '已失败', color: 'error' },
  completed: { label: '已完成', color: 'success' },
};

export const WORKER_STATUS_BADGE_MAP: Record<
  WorkerHealthStatus,
  { badgeStatus: 'success' | 'warning' | 'error' | 'default'; label: string; color: string }
> = {
  online: { badgeStatus: 'success', label: 'Online 在线', color: 'success' },
  stale: { badgeStatus: 'warning', label: 'Stale 延迟', color: 'warning' },
  offline: { badgeStatus: 'error', label: 'Offline 离线', color: 'error' },
};

export const TASK_LOG_LEVEL_MAP: Record<
  TaskLogLevel,
  { color: string; label: string }
> = {
  debug: { color: 'default', label: 'DEBUG' },
  info: { color: 'blue', label: 'INFO' },
  warning: { color: 'orange', label: 'WARN' },
  error: { color: 'red', label: 'ERROR' },
};

export const CANONICAL_JOB_CAPABILITIES: Record<string, TaskCapabilities> = {
  'fclones-scan': {
    supports_pause: false,
    supports_resume: false,
    supports_cancel: true,
    supports_retry: true,
  },
  'index-root': {
    supports_pause: false,
    supports_resume: false,
    supports_cancel: false,
    supports_retry: true,
  },
};

export function computeProgressPercentage(
  current: number,
  total: number,
  backendPercent?: number | null
): number | null {
  if (total <= 0) {
    return null;
  }
  if (backendPercent !== null && backendPercent !== undefined) {
    return Math.min(100, Math.max(0, Math.round(backendPercent)));
  }
  const calc = Math.round((current / total) * 100);
  return Math.min(100, Math.max(0, calc));
}

export function isProgressIndeterminate(total: number, percent?: number | null): boolean {
  return total <= 0 || percent === null || percent === undefined;
}
