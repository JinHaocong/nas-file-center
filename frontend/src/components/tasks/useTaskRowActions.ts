import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { getStructuredApiError } from '../../api/errors';
import { tasksApi } from '../../api/tasks';
import { sqliteIdText } from '../../utils/sqliteId';
import { getTaskActionAvailability } from './task_actions';

import type { TaskItem } from '../../types/task';

export type TaskRowAction = 'pause' | 'resume';

export type TaskRowActionFeedback =
  | { action: TaskRowAction; phase: 'pending' }
  | { action: TaskRowAction; phase: 'failed'; message: string; retryable: boolean };

/** Keep each command and its feedback attached to the exact task across pagination. */
export function useTaskRowActions() {
  const queryClient = useQueryClient();
  const locked = useRef(new Set<string>());
  const [feedbackById, setFeedbackById] = useState<Record<string, TaskRowActionFeedback>>({});
  const mutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: TaskRowAction }) => (
      action === 'pause' ? tasksApi.pauseTask(id) : tasksApi.resumeTask(id)
    ),
    retry: false,
  });

  /** Wait for the authoritative queue refresh before allowing another operation. */
  async function dispatch(task: TaskItem, action: TaskRowAction) {
    const id = sqliteIdText(task.id);
    if (!id || locked.current.has(id) || !getTaskActionAvailability(task, action).enabled) return;
    locked.current.add(id);
    setFeedbackById(previous => ({ ...previous, [id]: { action, phase: 'pending' } }));
    let failure: Extract<TaskRowActionFeedback, { phase: 'failed' }> | undefined;
    try {
      await mutation.mutateAsync({ id, action });
    } catch (error) {
      const { message, status } = getStructuredApiError(error);
      failure = {
        action, phase: 'failed', message,
        retryable: status === undefined || status === 0 || status === 408 || status === 429 || status >= 500,
      };
    } finally {
      try {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['tasksList'] }),
          queryClient.invalidateQueries({ queryKey: ['taskDetail', id] }),
          queryClient.invalidateQueries({ queryKey: ['taskLogs', id] }),
        ]);
      } finally {
        locked.current.delete(id);
        setFeedbackById(previous => {
          const next = { ...previous };
          if (failure) next[id] = failure;
          else delete next[id];
          return next;
        });
      }
    }
  }

  return { feedbackById, dispatch };
}
