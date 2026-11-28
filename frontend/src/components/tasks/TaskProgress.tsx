import React from 'react';
import dayjs from 'dayjs';

import { ProgressMotionTrack } from '../ui/ProgressMotionTrack';

import type { TaskProgress as TaskProgressType, TaskStatus } from '../../types/task';
import { computeProgressPercentage, calculateTaskEta } from './task_utils';

interface Props {
  progress: TaskProgressType;
  status?: TaskStatus | string;
  size?: 'small' | 'default';
  showDetails?: boolean;
  /** The containing header already shows task status. */
  summarized?: boolean;
  /** The ledger shows progress and actual speed in a stable, compact row. */
  compact?: boolean;
  reportedSpeed?: string | null;
  startedAt?: string | null;
  now?: dayjs.Dayjs;
}

export const TaskProgress: React.FC<Props> = ({
  progress, status, size = 'small', showDetails = false, summarized = false, compact = false,
  reportedSpeed, startedAt, now,
}) => {
  const current = progress?.current || 0;
  const total = progress?.total || 0;
  const message = reportedSpeed ? null : progress?.message;
  const percent = computeProgressPercentage(current, total, progress?.percent);
  const eta = compact ? null : calculateTaskEta(status, current, total, startedAt, progress?.percent, now);
  const etaText = eta && (!summarized || status === 'queued' || status === 'running')
    ? 'ETA: ' + eta.text : undefined;
  const timing = reportedSpeed
    ? <><span className="nfc-v2-task-speed" title="复制速度">{reportedSpeed}</span>{etaText && ' · ' + etaText}</>
    : etaText;

  /** Keep the primary count and the live metric aligned in both layouts. */
  const meta = (primary: React.ReactNode, secondary?: React.ReactNode) => (
    <div className="nfc-task-progress-meta">
      <span>{primary}</span>
      {secondary !== undefined && <span>{secondary}</span>}
    </div>
  );

  /** Show terminal status only when it is not displayed in the containing header. */
  const terminal = (
    label: string,
    tone: 'success' | 'danger' | 'warning' | 'muted',
    countLabel?: string,
  ) => (
    <div className={'nfc-task-progress nfc-task-progress-' + tone}>
      {summarized ? meta(countLabel || message || '暂无进度记录', countLabel ? message : undefined)
        : <>
          <span className="nfc-task-progress-status">{label}{countLabel ? ' (' + countLabel + ')' : ''}</span>
          {meta(etaText, message ? '· ' + message : undefined)}
        </>}
    </div>
  );

  if (total > 0 && percent !== null) {
    const tone = status === 'failed' ? 'danger' :
      status === 'completed' ? 'success' : status === 'running' ? 'active' : 'normal';
    return (
      <div className={'nfc-task-progress nfc-task-progress-bar nfc-v2-progress-' + tone +
        (compact ? ' is-ledger-progress' : '') +
        (showDetails ? ' is-detailed' : '') + (size === 'small' ? ' is-small' : '')}>
        <div className="nfc-v2-progress-track">
          <ProgressMotionTrack value={percent}>
            <progress className="nfc-v2-native-progress" max={100} value={percent}
              aria-label="任务完成进度">{percent}%</progress>
          </ProgressMotionTrack>
          <span className="nfc-v2-progress-percent">{percent}%</span>
        </div>
        {meta(
          current + ' / ' + total + (showDetails ? ' (' + percent + '%)' : ''),
          timing,
        )}
        {!compact && message && (
          <span className="nfc-task-progress-message" title={message}>{message}</span>
        )}
      </div>
    );
  }

  if (compact) {
    const summary = current > 0 ? current + ' 项' : status === 'running' ? '进度未知' : '—';
    return <div className="nfc-task-progress is-ledger-progress">{meta(summary, timing)}</div>;
  }

  if (status === 'running') {
    return (
      <div className="nfc-task-progress nfc-task-progress-running">
        <div className="nfc-task-progress-live" role="status">
          <span className="nfc-v2-progress-spinner" aria-hidden="true" />
          <span title={message || '正在执行...'}>{message || '正在执行...'}</span>
        </div>
        {meta('进度未知' + (current > 0 ? ' (' + current + ' 项)' : ''), timing)}
      </div>
    );
  }

  if (status === 'completed') {
    return terminal('已完成', 'success', current > 0 ? current + ' 项' : '');
  }
  if (status === 'failed') {
    return terminal('已失败', 'danger', current > 0 ? current + ' 项' : '');
  }
  if (status === 'cancelled') {
    return terminal('已取消', 'muted', current > 0 ? current + ' 项' : '');
  }
  if (status === 'paused') {
    return terminal('已暂停', 'warning', current > 0 ? '已处理: ' + current + ' 项' : '');
  }
  if (status === 'cancel_requested') {
    return terminal('正在取消...', 'warning', current > 0 ? current + ' 项' : '');
  }

  return (
    <div className="nfc-task-progress nfc-task-progress-muted">
      <span className="nfc-task-progress-status">{message || '等待 Worker 执行...'}</span>
      {meta(etaText, current > 0 ? '· 已处理 ' + current + ' 项' : undefined)}
    </div>
  );
};
