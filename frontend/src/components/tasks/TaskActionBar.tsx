import React, { useState } from 'react';
import { Space, Button, Popconfirm, Tooltip, message, notification } from 'antd';
import {
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TaskDetail, TaskItem } from '../../types/task';
import { getTaskActionAvailability, TaskAction } from './task_actions';

interface Props {
  task: TaskItem | TaskDetail;
  onViewTask?: (taskId: number) => void;
}

export const TaskActionBar: React.FC<Props> = ({ task, onViewTask }) => {
  const queryClient = useQueryClient();
  const [activeAction, setActiveAction] = useState<TaskAction | null>(null);

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
    onSuccess: async (res) => {
      await invalidateTaskQueries();
      if (res.status === 'paused') {
        message.success('任务已暂停');
      } else {
        message.success('暂停请求已提交');
      }
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      message.error(error.message || '暂停操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const resumeMutation = useMutation({
    mutationFn: () => tasksApi.resumeTask(task.id),
    onMutate: () => setActiveAction('resume'),
    onSuccess: async () => {
      await invalidateTaskQueries();
      message.success('任务已恢复并重新进入队列');
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      message.error(error.message || '恢复操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const cancelMutation = useMutation({
    mutationFn: () => tasksApi.cancelTask(task.id),
    onMutate: () => setActiveAction('cancel'),
    onSuccess: async (res) => {
      await invalidateTaskQueries();
      if (res.status === 'cancel_requested') {
        message.info('取消请求已提交，等待 Worker 安全停止');
      } else {
        message.success('任务已取消');
      }
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      message.error(error.message || '取消操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const retryMutation = useMutation({
    mutationFn: () => tasksApi.retryTask(task.id),
    onMutate: () => setActiveAction('retry'),
    onSuccess: async (res) => {
      await invalidateTaskQueries();
      const newJobId = res.job.id;
      notification.success({
        message: '重试任务已创建',
        description: `已为失败任务 #${task.id} 创建新的排队任务 #${newJobId}。`,
        btn: onViewTask ? (
          <Button
            type="primary"
            size="small"
            onClick={() => {
              notification.destroy();
              onViewTask(newJobId);
            }}
          >
            查看任务 #{newJobId}
          </Button>
        ) : undefined,
        duration: 8,
      });
    },
    onError: async (error: Error) => {
      await invalidateTaskQueries();
      message.error(error.message || '重试操作失败');
    },
    onSettled: () => setActiveAction(null),
  });

  const isAnyPending = activeAction !== null;

  const pauseAvail = getTaskActionAvailability(task, 'pause');
  const resumeAvail = getTaskActionAvailability(task, 'resume');
  const cancelAvail = getTaskActionAvailability(task, 'cancel');
  const retryAvail = getTaskActionAvailability(task, 'retry');

  const cancelDescription =
    task.status === 'running'
      ? '取消请求会发送给 Worker，任务将在下一个安全 checkpoint 停止，可能不会立即变成已取消。'
      : '确认取消该任务？';

  return (
    <Space wrap size={[12, 12]}>
      {/* 1. Pause Action */}
      <Tooltip title={!pauseAvail.enabled ? pauseAvail.reason : undefined}>
        <span>
          <Button
            icon={<PauseCircleOutlined />}
            disabled={!pauseAvail.enabled || isAnyPending}
            loading={activeAction === 'pause'}
            onClick={() => pauseMutation.mutate()}
          >
            暂停
          </Button>
        </span>
      </Tooltip>

      {/* 2. Resume Action */}
      <Tooltip title={!resumeAvail.enabled ? resumeAvail.reason : undefined}>
        <span>
          <Button
            icon={<PlayCircleOutlined />}
            disabled={!resumeAvail.enabled || isAnyPending}
            loading={activeAction === 'resume'}
            onClick={() => resumeMutation.mutate()}
          >
            恢复
          </Button>
        </span>
      </Tooltip>

      {/* 3. Cancel Action (Secondary Confirmation Required) */}
      <Tooltip title={!cancelAvail.enabled ? cancelAvail.reason : undefined}>
        <span>
          <Popconfirm
            title={`确认取消任务 #${task.id}？`}
            description={
              <div style={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                {cancelDescription}
              </div>
            }
            okText="确认取消"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            disabled={!cancelAvail.enabled || isAnyPending}
            onConfirm={() => cancelMutation.mutate()}
          >
            <Button
              danger
              icon={<StopOutlined />}
              disabled={!cancelAvail.enabled || isAnyPending}
              loading={activeAction === 'cancel'}
            >
              取消
            </Button>
          </Popconfirm>
        </span>
      </Tooltip>

      {/* 4. Retry Action (Secondary Confirmation Required) */}
      <Tooltip title={!retryAvail.enabled ? retryAvail.reason : undefined}>
        <span>
          <Popconfirm
            title={`确认重试任务 #${task.id}？`}
            description={
              <div style={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                原失败任务会保留，系统将创建一个新的排队任务。
              </div>
            }
            okText="确认重试"
            cancelText="取消"
            disabled={!retryAvail.enabled || isAnyPending}
            onConfirm={() => retryMutation.mutate()}
          >
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              disabled={!retryAvail.enabled || isAnyPending}
              loading={activeAction === 'retry'}
            >
              重试
            </Button>
          </Popconfirm>
        </span>
      </Tooltip>
    </Space>
  );
};
