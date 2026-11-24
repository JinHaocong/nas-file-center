import type { TaskDetail } from '../../types/task';
import { sqliteIdText } from '../../utils/sqliteId';

/** Link only to records actually identified by this job's backend payload. */
export function taskSourceLink(task: Pick<TaskDetail, 'id' | 'job_type' | 'payload'>): { href: string; label: string } | null {
  const payload = task.payload || {};
  if (task.job_type === 'batch-plan-execute' || task.job_type === 'media-sort-plan-stage') {
    const id = sqliteIdText(payload.plan_id);
    return id ? { href: '/plans/' + id, label: '查看来源计划 #' + id } : null;
  }
  if (task.job_type === 'fclones-scan') {
    const id = sqliteIdText(payload.scan_job_id);
    return id ? { href: '/scans/' + id, label: '查看来源扫描 #' + id } : null;
  }
  const id = sqliteIdText(task.id);
  if (id && task.job_type === 'media-organizer-preview') {
    return { href: '/batch?operation=media-organize&preview=' + id, label: '查看整理预览' };
  }
  if (id && task.job_type === 'media-organizer-batch') {
    return { href: '/batch?operation=media-organize&batch=' + id, label: '查看整理报告' };
  }
  return null;
}
