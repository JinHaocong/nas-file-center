import dayjs from 'dayjs';
import {
  TaskStatus,
  WorkerHealthStatus,
  TaskLogLevel,
  TaskCapabilities,
} from '../../types/task';
import { formatDuration } from '../../utils/format';

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

export interface TaskEtaResult {
  etaSeconds: number | null;
  text: string;
  isUnknown: boolean;
}

export interface TaskEtaOptions {
  status?: TaskStatus | string;
  current?: number | null;
  total?: number | null;
  startedAt?: string | null;
  percent?: number | null;
  now?: dayjs.Dayjs;
}

export function calculateTaskEta(
  statusOrOptions?: TaskStatus | string | TaskEtaOptions,
  currentArg?: number | null,
  totalArg?: number | null,
  startedAtArg?: string | null,
  percentArg?: number | null,
  nowArg?: dayjs.Dayjs
): TaskEtaResult {
  let status: TaskStatus | string | undefined;
  let curr: number | null | undefined;
  let tot: number | null | undefined;
  let startStr: string | null | undefined;
  let pct: number | null | undefined;
  let now: dayjs.Dayjs | undefined;

  if (typeof statusOrOptions === 'string') {
    status = statusOrOptions;
    curr = currentArg;
    tot = totalArg;
    startStr = startedAtArg;
    pct = percentArg;
    now = nowArg;
  } else if (statusOrOptions && typeof statusOrOptions === 'object') {
    status = statusOrOptions.status;
    curr = statusOrOptions.current;
    tot = statusOrOptions.total;
    startStr = statusOrOptions.startedAt;
    pct = statusOrOptions.percent;
    now = statusOrOptions.now;
  } else {
    status = undefined;
    curr = currentArg;
    tot = totalArg;
    startStr = startedAtArg;
    pct = percentArg;
    now = nowArg;
  }

  // Case 6: Completed deterministic behavior
  if (status === 'completed') {
    return { etaSeconds: 0, text: '已完成', isUnknown: false };
  }

  // Case 7: Failed or Cancelled - ETA unavailable
  if (status === 'failed' || status === 'cancelled') {
    return { etaSeconds: null, text: '不可用', isUnknown: true };
  }

  // Case 8: Paused - ETA paused
  if (status === 'paused') {
    return { etaSeconds: null, text: '已暂停', isUnknown: true };
  }

  if (status === 'cancel_requested') {
    return { etaSeconds: null, text: '正在取消', isUnknown: true };
  }

  // Non-running state (e.g. queued)
  if (status !== 'running') {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  // 1. total validity: total unknown (total <= 0 or null/undefined)
  const totalVal = tot ?? 0;
  if (totalVal <= 0) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  // 2. percent validity: percent unknown or missing
  if (pct === null || pct === undefined) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  // 3. current validity: current <= 0 (no velocity sample)
  const currentVal = curr ?? 0;
  if (currentVal <= 0) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  // 4. current >= total: deterministic completion check before started_at/elapsed
  if (currentVal >= totalVal) {
    return { etaSeconds: 0, text: '0s', isUnknown: false };
  }

  // 5. started_at validity: missing or invalid
  if (!startStr) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  let s = String(startStr).trim();
  if (!s.endsWith('Z') && !s.includes('+') && !s.includes('GMT')) {
    s = s.replace(' ', 'T') + 'Z';
  }
  const start = dayjs(s);
  if (!start.isValid()) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  // 6. elapsed validity
  const currentTime = now || dayjs();
  const elapsedSeconds = currentTime.diff(start, 'second');
  if (!Number.isFinite(elapsedSeconds) || elapsedSeconds <= 0) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  // 7. calculate ETA
  const remaining = totalVal - currentVal;
  const rawEta = (elapsedSeconds * remaining) / currentVal;

  if (!Number.isFinite(rawEta) || Number.isNaN(rawEta) || rawEta < 0) {
    return { etaSeconds: null, text: '未知', isUnknown: true };
  }

  const etaSeconds = Math.max(0, Math.round(rawEta));
  return {
    etaSeconds,
    text: formatDuration(etaSeconds),
    isUnknown: false,
  };
}
