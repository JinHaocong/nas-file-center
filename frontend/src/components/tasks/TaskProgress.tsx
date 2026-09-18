import React from 'react';
import { Progress, Typography, Spin } from 'antd';
import dayjs from 'dayjs';
import { TaskProgress as TaskProgressType, TaskStatus } from '../../types/task';
import { computeProgressPercentage, calculateTaskEta } from './task_utils';

const { Text } = Typography;

interface Props {
  progress: TaskProgressType;
  status?: TaskStatus | string;
  size?: 'small' | 'default';
  showDetails?: boolean;
  startedAt?: string | null;
  now?: dayjs.Dayjs;
}

export const TaskProgress: React.FC<Props> = ({
  progress,
  status,
  size = 'small',
  showDetails = false,
  startedAt,
  now,
}) => {
  const current = progress?.current || 0;
  const total = progress?.total || 0;
  const message = progress?.message;
  const percent = computeProgressPercentage(current, total, progress?.percent);
  const eta = calculateTaskEta(status, current, total, startedAt, progress?.percent, now);

  const meta = (primary: React.ReactNode, secondary?: React.ReactNode) => (
    <div className="nfc-task-progress-meta">
      <Text type="secondary">{primary}</Text>
      {secondary !== undefined && <Text type="secondary">{secondary}</Text>}
    </div>
  );

  const terminal = (
    label: string,
    tone: 'success' | 'danger' | 'warning' | 'muted',
    countLabel?: string,
  ) => (
    <div className={`nfc-task-progress nfc-task-progress-${tone}`}>
      <Text className="nfc-task-progress-status">
        {label}{countLabel || ''}
      </Text>
      {meta(`ETA: ${eta.text}`, message ? `· ${message}` : undefined)}
    </div>
  );

  if (total > 0 && percent !== null) {
    let progressStatus: 'success' | 'exception' | 'normal' | 'active' | undefined;
    if (status === 'failed') progressStatus = 'exception';
    else if (status === 'completed') progressStatus = 'success';
    else if (status === 'running') progressStatus = 'active';

    return (
      <div className={`nfc-task-progress nfc-task-progress-bar ${showDetails ? 'is-detailed' : ''}`}>
        <Progress percent={percent} size={size} status={progressStatus} />
        {meta(
          `${current} / ${total}${showDetails ? ` (${percent}%)` : ''}`,
          `ETA: ${eta.text}`,
        )}
        {message && (
          <Text
            type="secondary"
            ellipsis={{ tooltip: message }}
            className="nfc-task-progress-message"
          >
            {message}
          </Text>
        )}
      </div>
    );
  }

  if (status === 'running') {
    return (
      <div className="nfc-task-progress nfc-task-progress-running">
        <div className="nfc-task-progress-live">
          <Spin size="small" />
          <Text ellipsis={{ tooltip: message || '正在执行...' }}>
            {message || '正在执行...'}
          </Text>
        </div>
        {meta(`进度未知${current > 0 ? ` (${current} 项)` : ''}`, `ETA: ${eta.text}`)}
      </div>
    );
  }

  if (status === 'completed') {
    return terminal('已完成', 'success', current > 0 ? ` (${current} 项)` : '');
  }
  if (status === 'failed') {
    return terminal('已失败', 'danger', current > 0 ? ` (${current} 项)` : '');
  }
  if (status === 'cancelled') {
    return terminal('已取消', 'muted', current > 0 ? ` (${current} 项)` : '');
  }
  if (status === 'paused') {
    return terminal('已暂停', 'warning', current > 0 ? ` (已处理: ${current} 项)` : '');
  }
  if (status === 'cancel_requested') {
    return terminal('正在取消...', 'warning', current > 0 ? ` (${current} 项)` : '');
  }

  return (
    <div className="nfc-task-progress nfc-task-progress-muted">
      <Text className="nfc-task-progress-status">
        {message || '等待 Worker 执行...'}
      </Text>
      {meta(`ETA: ${eta.text}`, current > 0 ? `· 已处理 ${current} 项` : undefined)}
    </div>
  );
};
