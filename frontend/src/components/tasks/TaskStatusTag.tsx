import React from 'react';
import type { TaskStatus } from '../../types/task';
import { TASK_STATUS_CONFIG } from './task_utils';
import { StatusBadge } from '../ui/StatusBadge';

interface Props { status: TaskStatus | string; }

/** Reuse native semantic status presentation; do not carry Ant Design's Tag into task views. */
export const TaskStatusTag: React.FC<Props> = ({ status }) => {
  const config = TASK_STATUS_CONFIG[status as TaskStatus];
  return <StatusBadge status={status || 'unknown'} label={config?.label || status || '-'} />;
};
