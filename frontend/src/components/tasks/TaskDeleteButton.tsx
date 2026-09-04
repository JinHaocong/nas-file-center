import React from 'react';
import { Button, Popconfirm, Tooltip, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TaskDetail, TaskItem } from '../../types/task';
import { getTaskDeleteAvailability } from './task_cleanup';

interface Props {
  task: TaskItem | TaskDetail;
  onSuccess?: () => void;
  size?: 'small' | 'middle';
  type?: 'link' | 'text' | 'default' | 'primary';
  danger?: boolean;
}

export const TaskDeleteButton: React.FC<Props> = ({
  task,
  onSuccess,
  size = 'middle',
  type = 'default',
  danger = true,
}) => {
  const queryClient = useQueryClient();
  const availability = getTaskDeleteAvailability(task);

  const deleteMutation = useMutation({
    mutationFn: () => tasksApi.deleteTask(task.id),
    onSuccess: async () => {
      message.success(`任务 #${task.id} 已删除`);
      await queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      queryClient.removeQueries({ queryKey: ['taskDetail', task.id] });
      queryClient.removeQueries({ queryKey: ['taskLogs', task.id] });
      onSuccess?.();
    },
    onError: async (err: Error) => {
      await queryClient.invalidateQueries({ queryKey: ['tasksList'] });
      message.error(err.message || '删除任务失败');
    },
  });

  if (!availability.enabled) {
    return (
      <Tooltip title={availability.reason}>
        <span>
          <Button
            size={size}
            type={type}
            danger={danger}
            icon={<DeleteOutlined />}
            disabled
          >
            删除
          </Button>
        </span>
      </Tooltip>
    );
  }

  return (
    <Popconfirm
      title={`确认删除任务 #${task.id}？`}
      description="删除后将同时清除该任务的事件日志。该操作不会删除 NAS 上的任何文件，也不会删除 Audit 审计记录。"
      okText="确认删除"
      cancelText="取消"
      okButtonProps={{ danger: true, loading: deleteMutation.isPending }}
      onConfirm={() => deleteMutation.mutate()}
    >
      <Button
        size={size}
        type={type}
        danger={danger}
        icon={<DeleteOutlined />}
        loading={deleteMutation.isPending}
      >
        删除
      </Button>
    </Popconfirm>
  );
};
