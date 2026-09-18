import React from 'react';
import { STATUS_MAP } from '../../utils/constants';

type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const toneByStatus: Record<string, StatusTone> = {
  queued: 'neutral',
  running: 'info',
  paused: 'warning',
  cancel_requested: 'warning',
  cancelled: 'neutral',
  completed: 'success',
  failed: 'danger',
  draft: 'neutral',
  frozen: 'info',
  validating: 'info',
  ready: 'success',
  partial: 'warning',
  executing: 'info',
  planned: 'neutral',
  validated: 'success',
  skipped: 'warning',
  stale: 'danger',
  expired: 'danger',
};

const fallbackLabels: Record<string, string> = {
  expired: '已过期',
};

interface StatusBadgeProps {
  status: string;
  label?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, label }) => {
  const tone = toneByStatus[status] || 'neutral';
  const resolvedLabel = label || STATUS_MAP[status]?.label || fallbackLabels[status] || status;
  const isLive = status === 'running' || status === 'executing' || status === 'validating';

  return (
    <span className={`nfc-status-badge nfc-status-${tone}${isLive ? ' nfc-status-live' : ''}`}>
      <span className="nfc-status-dot" aria-hidden="true" />
      {resolvedLabel}
    </span>
  );
};
