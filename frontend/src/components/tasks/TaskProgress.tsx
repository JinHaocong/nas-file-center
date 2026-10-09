import React from 'react';
import dayjs from 'dayjs';
import type { TaskProgress as TaskProgressType, TaskStatus } from '../../types/task';
import { computeProgressPercentage, calculateTaskEta } from './task_utils';

interface Props {
  progress: TaskProgressType;
  status?: TaskStatus | string;
  size?: 'small' | 'default';
  showDetails?: boolean;
  startedAt?: string | null;
  now?: dayjs.Dayjs;
}

export const TaskProgress: React.FC<Props> = ({
  progress, status, size = 'small', showDetails = false, startedAt, now,
}) => {
  const current = progress?.current || 0;
  const total = progress?.total || 0;
  const message = progress?.message;
  const percent = computeProgressPercentage(current, total, progress?.percent);
  const eta = calculateTaskEta(status, current, total, startedAt, progress?.percent, now);

  const meta = (primary: React.ReactNode, secondary?: React.ReactNode) => (
    <div className="nfc-task-progress-meta">
      <span>{primary}</span>
      {secondary !== undefined && <span>{secondary}</span>}
    </div>
  );

  const terminal = (
    label: string,
    tone: 'success' | 'danger' | 'warning' | 'muted',
    countLabel?: string,
  ) => (
    <div className={'nfc-task-progress nfc-task-progress-' + tone}>
      <span className="nfc-task-progress-status">{label}{countLabel || ''}</span>
      {meta('ETA: ' + eta.text, message ? '· ' + message : undefined)}
    </div>
  );

  if (total > 0 && percent !== null) {
    const tone = status === 'failed' ? 'danger' :
      status === 'completed' ? 'success' : status === 'running' ? 'active' : 'normal';
    return (
      <div className={'nfc-task-progress nfc-task-progress-bar nfc-v2-progress-' + tone +
        (showDetails ? ' is-detailed' : '') + (size === 'small' ? ' is-small' : '')}>
        <div className="nfc-v2-progress-track">
          <progress className="nfc-v2-native-progress" max={100} value={percent}
            aria-label="任务完成进度">{percent}%</progress>
          <span className="nfc-v2-progress-percent">{percent}%</span>
        </div>
        {meta(
          current + ' / ' + total + (showDetails ? ' (' + percent + '%)' : ''),
          'ETA: ' + eta.text,
        )}
        {message && (
          <span className="nfc-task-progress-message" title={message}>{message}</span>
        )}
      </div>
    );
  }

  if (status === 'running') {
    return (
      <div className="nfc-task-progress nfc-task-progress-running">
        <div className="nfc-task-progress-live" role="status">
          <span className="nfc-v2-progress-spinner" aria-hidden="true" />
          <span title={message || '正在执行...'}>{message || '正在执行...'}</span>
        </div>
        {meta('进度未知' + (current > 0 ? ' (' + current + ' 项)' : ''), 'ETA: ' + eta.text)}
      </div>
    );
  }

  if (status === 'completed') {
    return terminal('已完成', 'success', current > 0 ? ' (' + current + ' 项)' : '');
  }
  if (status === 'failed') {
    return terminal('已失败', 'danger', current > 0 ? ' (' + current + ' 项)' : '');
  }
  if (status === 'cancelled') {
    return terminal('已取消', 'muted', current > 0 ? ' (' + current + ' 项)' : '');
  }
  if (status === 'paused') {
    return terminal('已暂停', 'warning', current > 0 ? ' (已处理: ' + current + ' 项)' : '');
  }
  if (status === 'cancel_requested') {
    return terminal('正在取消...', 'warning', current > 0 ? ' (' + current + ' 项)' : '');
  }

  return (
    <div className="nfc-task-progress nfc-task-progress-muted">
      <span className="nfc-task-progress-status">{message || '等待 Worker 执行...'}</span>
      {meta('ETA: ' + eta.text, current > 0 ? '· 已处理 ' + current + ' 项' : undefined)}
    </div>
  );
};
