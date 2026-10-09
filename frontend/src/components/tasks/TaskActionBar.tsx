import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import type { TaskDetail, TaskItem } from '../../types/task';
import { getTaskActionAvailability, type TaskAction } from './task_actions';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';

interface Props {
  task: TaskItem | TaskDetail;
  onViewTask?: (taskId: number) => void;
}

export const TaskActionBar: React.FC<Props> = ({ task, onViewTask }) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const [activeAction, setActiveAction] = useState<TaskAction | null>(null);
  const [confirmAction, setConfirmAction] = useState<'cancel' | 'retry' | null>(null);
  const [createdRetryId, setCreatedRetryId] = useState<number | null>(null);

  const invalidateTaskQueries = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['tasksList'] }),
      queryClient.invalidateQueries({ queryKey: ['taskDetail', task.id] }),
      queryClient.invalidateQueries({ queryKey: ['taskLogs', task.id] }),
    ]);
  };

  const pauseMutation = useMutation({
    mutationFn: () => tasksApi.pauseTask(task.id),
    onMutate: () => setActiveAction('pause'),
    onSuccess: async res => {
      await invalidateTaskQueries();
      toast.success(res.status === 'paused' ? '任务已暂停' : '暂停请求已提交');
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      toast.error(error.message || '暂停操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const resumeMutation = useMutation({
    mutationFn: () => tasksApi.resumeTask(task.id),
    onMutate: () => setActiveAction('resume'),
    onSuccess: async () => {
      await invalidateTaskQueries();
      toast.success('任务已恢复并重新进入队列');
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      toast.error(error.message || '恢复操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const cancelMutation = useMutation({
    mutationFn: () => tasksApi.cancelTask(task.id),
    onMutate: () => setActiveAction('cancel'),
    onSuccess: async res => {
      await invalidateTaskQueries();
      toast.info(res.status === 'cancel_requested'
        ? '取消请求已提交，等待 Worker 安全停止' : '任务已取消');
      setConfirmAction(null);
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      toast.error(error.message || '取消操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const retryMutation = useMutation({
    mutationFn: () => tasksApi.retryTask(task.id),
    onMutate: () => setActiveAction('retry'),
    onSuccess: async res => {
      await invalidateTaskQueries();
      setCreatedRetryId(res.job.id);
      toast.success('重试任务 #' + res.job.id + ' 已创建');
      setConfirmAction(null);
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      toast.error(error.message || '重试操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const isAnyPending = activeAction !== null;
  const pauseAvail = getTaskActionAvailability(task, 'pause');
  const resumeAvail = getTaskActionAvailability(task, 'resume');
  const cancelAvail = getTaskActionAvailability(task, 'cancel');
  const retryAvail = getTaskActionAvailability(task, 'retry');

  const confirmDescription = confirmAction === 'cancel'
    ? task.status === 'running'
      ? '取消请求会发送给 Worker，任务将在下一个安全 checkpoint 停止，可能不会立即变成已取消。'
      : '确认取消该任务？'
    : '原失败任务会保留，系统将创建一个新的排队任务。';

  const confirm = () => {
    if (isAnyPending) return;
    if (confirmAction === 'cancel' && cancelAvail.enabled) cancelMutation.mutate();
    if (confirmAction === 'retry' && retryAvail.enabled) retryMutation.mutate();
  };

  return (
    <div className="nfc-task-action-bar nfc-v2-task-actions">
      <span title={!pauseAvail.enabled ? pauseAvail.reason || undefined : undefined}>
        <ConsoleButton disabled={!pauseAvail.enabled || isAnyPending}
          loading={activeAction === 'pause'} onClick={() => pauseMutation.mutate()}>
          暂停
        </ConsoleButton>
      </span>
      <span title={!resumeAvail.enabled ? resumeAvail.reason || undefined : undefined}>
        <ConsoleButton disabled={!resumeAvail.enabled || isAnyPending}
          loading={activeAction === 'resume'} onClick={() => resumeMutation.mutate()}>
          恢复
        </ConsoleButton>
      </span>
      <span title={!cancelAvail.enabled ? cancelAvail.reason || undefined : undefined}>
        <ConsoleButton variant="danger"
          leadingIcon={<ConsoleIcon name="x" size={15} />}
          disabled={!cancelAvail.enabled || isAnyPending}
          loading={activeAction === 'cancel'}
          onClick={() => { if (cancelAvail.enabled) setConfirmAction('cancel'); }}>
          取消
        </ConsoleButton>
      </span>
      <span title={!retryAvail.enabled ? retryAvail.reason || undefined : undefined}>
        <ConsoleButton variant="primary"
          leadingIcon={<ConsoleIcon name="refresh" size={15} />}
          disabled={!retryAvail.enabled || isAnyPending}
          loading={activeAction === 'retry'}
          onClick={() => { if (retryAvail.enabled) setConfirmAction('retry'); }}>
          重试
        </ConsoleButton>
      </span>
      {createdRetryId !== null && (
        <div className="nfc-v2-retry-result" role="status">
          已为任务 #{task.id} 创建重试任务 #{createdRetryId}
          {onViewTask && (
            <ConsoleButton size="sm" variant="ghost"
              onClick={() => {
                const id = createdRetryId;
                setCreatedRetryId(null);
                onViewTask(id);
              }}>
              查看任务 #{createdRetryId}
            </ConsoleButton>
          )}
        </div>
      )}
      <ConsoleConfirmDialog
        open={confirmAction !== null}
        onOpenChange={next => { if (!next && !isAnyPending) setConfirmAction(null); }}
        title={confirmAction === 'cancel'
          ? '确认取消任务 #' + task.id + '？'
          : '确认重试任务 #' + task.id + '？'}
        description={<p>{confirmDescription}</p>}
        confirmText={confirmAction === 'cancel' ? '确认取消' : '确认重试'}
        onConfirm={confirm}
        busy={isAnyPending}
        disabled={confirmAction === 'cancel' ? !cancelAvail.enabled : !retryAvail.enabled}
        danger={confirmAction === 'cancel'}
      />
    </div>
  );
};
