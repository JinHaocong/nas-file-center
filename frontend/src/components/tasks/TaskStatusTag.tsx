import React from 'react';
import { Tag } from 'antd';
import { TaskStatus } from '../../types/task';
import { TASK_STATUS_CONFIG } from './task_utils';

interface Props {
  status: TaskStatus | string;
}

export const TaskStatusTag: React.FC<Props> = ({ status }) => {
  const config = TASK_STATUS_CONFIG[status as TaskStatus];
  if (!config) {
    return <Tag color="default">{status || '-'}</Tag>;
  }
  return <Tag color={config.color}>{config.label}</Tag>;
};
