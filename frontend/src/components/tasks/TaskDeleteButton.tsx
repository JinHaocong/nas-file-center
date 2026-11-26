import React, { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import type { TaskDetail, TaskItem } from '../../types/task';
import { formatReportCleanupFeedback, getTaskDeleteAvailability } from './task_cleanup';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';

interface Props {
  task: TaskItem | TaskDetail;
  onSuccess?: () => void;
  size?: 'small' | 'middle';
  type?: 'link' | 'text' | 'default' | 'primary';
  danger?: boolean;
}

export const TaskDeleteButton: React.FC<Props> = ({
  task, onSuccess, size = 'middle', type = 'default', danger = true,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const [open, setOpen] = useState(false);
  const deleteInFlight = useRef(false);
  const availability = getTaskDeleteAvailability(task);

  const deleteMutation = useMutation({
    mutationFn: () => tasksApi.deleteTask(task.id),
    onSuccess: async result => {
      const message = `任务 #${task.id} 已从列表移除`;
      const feedback = formatReportCleanupFeedback(result.report_cleanup);
      toast.success(feedback ? `${message}，${feedback}` : message);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tasksList'] }),
        queryClient.invalidateQueries({ queryKey: ['recentTasks'] }),
        queryClient.invalidateQueries({ queryKey: ['organizerReports'] }),
      ]);
      queryClient.removeQueries({ queryKey: ['taskDetail', String(task.id)] });
      queryClient.removeQueries({ queryKey: ['taskLogs', String(task.id)] });
      setOpen(false);
      onSuccess?.();
    },
    onError: async (err: Error) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tasksList'] }),
        queryClient.invalidateQueries({ queryKey: ['recentTasks'] }),
      ]);
      toast.error(err.message || '删除任务失败');
    },
  });

  const confirmDelete = async () => {
    // Acquire the lock synchronously, before React Query's pending state rerenders.
    if (!getTaskDeleteAvailability(task).enabled || deleteMutation.isPending || deleteInFlight.current) return;
    deleteInFlight.current = true;
    try {
      await deleteMutation.mutateAsync();
    } catch {
      // onError already owns the toast and task-list invalidation.
    } finally {
      deleteInFlight.current = false;
    }
  };

  return (
    <>
      <span title={!availability.enabled ? availability.reason || undefined : undefined}>
        <ConsoleButton
          size={size === 'small' ? 'sm' : 'md'}
          variant={type === 'link' || type === 'text' ? 'ghost' : danger ? 'danger' : 'secondary'}
          leadingIcon={<ConsoleIcon name="archive" size={15} />}
          disabled={!availability.enabled || deleteMutation.isPending}
          loading={deleteMutation.isPending}
          aria-label={'删除任务 #' + task.id}
          onClick={() => { if (availability.enabled && !deleteMutation.isPending && !deleteInFlight.current) setOpen(true); }}
        >删除</ConsoleButton>
      </span>
      <ConsoleConfirmDialog
        open={open}
        onOpenChange={next => { if (!deleteMutation.isPending && !deleteInFlight.current) setOpen(next); }}
        title={'确认删除任务 #' + task.id + '？'}
        description={
          <dl className="nfc-maintenance-impact nfc-maintenance-impact-list">
            <div><dt>移除任务</dt><dd>任务将从列表移除，可安全回收的智能整理报告会排队清理。</dd></div>
            <div><dt>保留内容</dt><dd>恢复所需资料、NAS 媒体文件和 Audit 审计记录会保留。</dd></div>
          </dl>
        }
        confirmText="确认删除"
        onConfirm={() => { void confirmDelete(); }}
        busy={deleteMutation.isPending}
        disabled={!availability.enabled || deleteMutation.isPending}
        danger
      />
    </>
  );
};
