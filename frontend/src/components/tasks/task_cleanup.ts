import type { OrganizerReportCleanupFeedback, TaskStatus } from '../../types/task';

export interface TaskDeleteAvailability {
  enabled: boolean;
  reason: string | null;
}

/** Describe the organizer report outcomes returned by task deletion. */
export function formatReportCleanupFeedback(cleanup?: OrganizerReportCleanupFeedback): string {
  if (!cleanup) return '';
  const messages: string[] = [];
  if (cleanup.queued_count > 0) messages.push(`${cleanup.queued_count} 项报告已排队回收`);
  if (cleanup.retained_count > 0) messages.push(`${cleanup.retained_count} 项报告保留恢复资料`);
  return messages.join('，');
}

export function getTaskDeleteAvailability(
  task: { status?: TaskStatus } | null | undefined
): TaskDeleteAvailability {
  if (!task || !task.status) {
    return { enabled: false, reason: '任务不存在' };
  }

  switch (task.status) {
    case 'completed':
    case 'failed':
    case 'cancelled':
      return { enabled: true, reason: null };
    case 'queued':
      return { enabled: false, reason: '排队中的任务不能删除' };
    case 'running':
      return { enabled: false, reason: '执行中的任务不能删除' };
    case 'paused':
      return { enabled: false, reason: '暂停中的任务不能删除，请先取消任务' };
    case 'cancel_requested':
      return { enabled: false, reason: '任务正在取消，请等待进入终态后再删除' };
    default:
      return { enabled: false, reason: '当前任务状态不支持删除' };
  }
}
