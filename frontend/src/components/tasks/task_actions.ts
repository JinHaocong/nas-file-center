import { TaskCapabilities, TaskStatus } from '../../types/task';

export type TaskAction = 'pause' | 'resume' | 'cancel' | 'retry';

export interface TaskActionAvailability {
  enabled: boolean;
  reason: string | null;
}

export interface TaskLike {
  status: TaskStatus;
  capabilities?: TaskCapabilities | null;
}

/**
 * Evaluates whether a given task action (pause, resume, cancel, retry) can be executed.
 * Follows strict Capability-driven rules + Backend status machine contract.
 *
 * Rules:
 * 1. Backend task.capabilities is the primary authority; if capability is false, action is disabled.
 * 2. If capability is supported, current task.status determines whether the transition is valid.
 * 3. Disabled actions always return a human-readable explanation distinguishing capability vs status restrictions.
 */
export function getTaskActionAvailability(
  task: TaskLike | null | undefined,
  action: TaskAction
): TaskActionAvailability {
  if (!task) {
    return { enabled: false, reason: '任务不存在' };
  }

  const { status, capabilities } = task;

  switch (action) {
    case 'pause': {
      if (!capabilities?.supports_pause) {
        return { enabled: false, reason: '此任务类型不支持暂停' };
      }
      if (status === 'paused') {
        return { enabled: false, reason: '任务已经暂停' };
      }
      if (status === 'cancel_requested') {
        return { enabled: false, reason: '当前任务正在取消' };
      }
      if (status === 'completed' || status === 'failed' || status === 'cancelled') {
        return { enabled: false, reason: '终态任务不可暂停' };
      }
      if (status === 'queued' || status === 'running') {
        return { enabled: true, reason: null };
      }
      return { enabled: false, reason: '当前状态不允许暂停' };
    }

    case 'resume': {
      if (!capabilities?.supports_resume) {
        return { enabled: false, reason: '此任务类型不支持恢复' };
      }
      if (status === 'paused') {
        return { enabled: true, reason: null };
      }
      if (status === 'cancel_requested') {
        return { enabled: false, reason: '当前任务正在取消' };
      }
      if (status === 'completed' || status === 'failed' || status === 'cancelled') {
        return { enabled: false, reason: '终态任务不可恢复' };
      }
      return { enabled: false, reason: '仅暂停状态的任务可以恢复' };
    }

    case 'cancel': {
      if (!capabilities?.supports_cancel) {
        return { enabled: false, reason: '此任务类型不支持取消' };
      }
      if (status === 'cancel_requested') {
        return { enabled: false, reason: '当前任务正在取消' };
      }
      if (status === 'cancelled') {
        return { enabled: false, reason: '任务已取消' };
      }
      if (status === 'completed' || status === 'failed') {
        return { enabled: false, reason: '终态任务不可取消' };
      }
      if (status === 'queued' || status === 'running' || status === 'paused') {
        return { enabled: true, reason: null };
      }
      return { enabled: false, reason: '当前状态不允许取消' };
    }

    case 'retry': {
      if (!capabilities?.supports_retry) {
        return { enabled: false, reason: '此任务类型不支持重试' };
      }
      if (status === 'failed') {
        return { enabled: true, reason: null };
      }
      if (status === 'running' || status === 'queued' || status === 'paused') {
        return { enabled: false, reason: '运行中或未失败的任务不可重试' };
      }
      if (status === 'completed') {
        return { enabled: false, reason: '已完成的任务无需重试' };
      }
      if (status === 'cancelled') {
        return { enabled: false, reason: '已取消的任务不可重试' };
      }
      return { enabled: false, reason: '仅失败任务可以重试' };
    }

    default:
      return { enabled: false, reason: '未知操作' };
  }
}
