import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import type { TaskDetail, TaskItem } from '../../types/task';
import { getTaskDeleteAvailability } from './task_cleanup';
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
  const availability = getTaskDeleteAvailability(task);

  const deleteMutation = useMutation({
    mutationFn: () => tasksApi.deleteTask(task.id),
    onSuccess: async () => {
      toast.success('任务 #' + task.id + ' 已删除');
      await queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      queryClient.removeQueries({ queryKey: ['taskDetail', task.id] });
      queryClient.removeQueries({ queryKey: ['taskLogs', task.id] });
      setOpen(false);
      onSuccess?.();
    },
    onError: async (err: Error) => {
      await queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      toast.error(err.message || '删除任务失败');
    },
  });

  const confirmDelete = () => {
    if (!availability.enabled || deleteMutation.isPending) return;
    deleteMutation.mutate();
  };

  return (
    <>
      <span title={!availability.enabled ? availability.reason || undefined : undefined}>
        <ConsoleButton
          size={size === 'small' ? 'sm' : 'md'}
          variant={type === 'link' || type === 'text' ? 'ghost' : danger ? 'danger' : 'secondary'}
          leadingIcon={<ConsoleIcon name="archive" size={15} />}
          disabled={!availability.enabled}
          loading={deleteMutation.isPending}
          aria-label={'删除任务 #' + task.id}
          onClick={() => { if (availability.enabled) setOpen(true); }}
        >删除</ConsoleButton>
      </span>
      <ConsoleConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={'确认删除任务 #' + task.id + '？'}
        description={
          <p>删除后将同时清除该任务的事件日志。该操作不会删除 NAS 上的任何文件，也不会删除 Audit 审计记录。</p>
        }
        confirmText="确认删除"
        onConfirm={confirmDelete}
        busy={deleteMutation.isPending}
        disabled={!availability.enabled}
        danger
      />
    </>
  );
};
