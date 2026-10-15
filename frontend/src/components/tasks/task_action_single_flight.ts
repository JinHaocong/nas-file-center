import { getTaskActionAvailability, type TaskAction, type TaskLike } from './task_actions';

/**
 * Feature-owned synchronous single-flight fence around a Task action.
 * The lock is acquired before awaiting React Query or React rendering;
 * backend capabilities/status and the server's state machine stay authoritative.
 */
export async function dispatchTaskActionOnce(
  lock: { current: boolean },
  task: TaskLike | null | undefined,
  action: TaskAction,
  mutateAsync: () => Promise<unknown>,
  onStart: () => void,
  onFinish: () => void,
): Promise<boolean> {
  if (lock.current || !getTaskActionAvailability(task, action).enabled) return false;
  lock.current = true;
  try {
    onStart();
    await mutateAsync();
    return true;
  } finally {
    lock.current = false;
    onFinish();
  }
}
