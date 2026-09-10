import { ResourcePolicyUpdate } from '../../types';

export const COMMON_TIMEZONES = [
  'UTC',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Taipei',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Australia/Sydney',
];

export interface ValidationResult {
  valid: boolean;
  error?: string;
}

export function validateResourcePolicyUpdate(payload: ResourcePolicyUpdate): ValidationResult {
  if (typeof payload.scan_threads !== 'number' || payload.scan_threads < 1 || payload.scan_threads > 32) {
    return { valid: false, error: '扫描线程上限必须为 1 到 32 之间的整数' };
  }
  if (typeof payload.hash_threads !== 'number' || payload.hash_threads < 1 || payload.hash_threads > 32) {
    return { valid: false, error: '哈希线程上限必须为 1 到 32 之间的整数' };
  }
  if (!['low', 'normal', 'unlimited'].includes(payload.io_limit)) {
    return { valid: false, error: 'I/O 压力限制值无效' };
  }
  if (!['normal', 'background'].includes(payload.job_priority)) {
    return { valid: false, error: '任务调度优先级值无效' };
  }
  if (!['limited', 'pause'].includes(payload.outside_window_mode)) {
    return { valid: false, error: '窗口外降级策略无效' };
  }
  if (payload.active_window_enabled) {
    if (!payload.active_window_start || !payload.active_window_end) {
      return { valid: false, error: '启用活跃时间窗口时，起始和结束时间均不能为空' };
    }
    const timeRegex = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (!timeRegex.test(payload.active_window_start) || !timeRegex.test(payload.active_window_end)) {
      return { valid: false, error: '时间格式必须为 HH:MM (例如 01:00)' };
    }
    if (payload.active_window_start === payload.active_window_end) {
      return { valid: false, error: '时间窗口起始时间与结束时间不能相同' };
    }
    if (!payload.active_window_timezone || !payload.active_window_timezone.trim()) {
      return { valid: false, error: '启用活跃时间窗口时必须选择有效时区' };
    }
  }
  return { valid: true };
}

export function getProfileDisplay(profile: string): { text: string; color: string } {
  switch (profile) {
    case 'full':
      return { text: '全速运行 (Full)', color: 'success' };
    case 'limited':
      return { text: '窗口外降速 (Limited - 1线程)', color: 'warning' };
    case 'pause':
      return { text: '窗口外暂停认领 (Pause)', color: 'error' };
    default:
      return { text: profile, color: 'default' };
  }
}
