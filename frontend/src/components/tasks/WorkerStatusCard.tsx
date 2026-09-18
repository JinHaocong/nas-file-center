import React from 'react';
import { Alert, Skeleton } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { formatDateTime, formatHeartbeatAge } from '../../utils/format';
import { WORKER_STATUS_BADGE_MAP } from './task_utils';

export const WorkerStatusCard: React.FC = () => {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['workerStatus'],
    queryFn: () => tasksApi.getWorkerStatus(),
    refetchInterval: 5000,
    retry: 1,
  });

  if (isError) {
    return (
      <div className="nfc-worker-panel">
        <Alert
          type="warning"
          showIcon
          message="Worker 状态暂不可用"
          description={
            typeof error === 'object' && error && 'message' in error
              ? String(error.message)
              : '无法连接到后台 Worker 状态服务，任务列表仍可正常查看。'
          }
        />
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <div className="nfc-worker-panel nfc-worker-panel-loading">
        <Skeleton active paragraph={{ rows: 1 }} />
      </div>
    );
  }

  const workerStatus = data?.status || 'offline';
  const badgeConfig = WORKER_STATUS_BADGE_MAP[workerStatus] || WORKER_STATUS_BADGE_MAP.offline;

  return (
    <section className="nfc-worker-panel nfc-worker-status-strip" aria-label="调度 Worker 状态">
      <div className="nfc-worker-primary">
        <span className={'nfc-worker-status nfc-worker-status-' + workerStatus}>
          <span className="nfc-status-dot" aria-hidden="true" />
          {badgeConfig.label}
        </span>
        <div>
          <div className="nfc-worker-eyebrow">Scheduler</div>
          <strong>调度 Worker</strong>
        </div>
      </div>

      <div className="nfc-worker-stats">
        <div className="nfc-worker-stat">
          <span>Worker ID</span>
          <strong className="nfc-mono">{data?.worker_id || '—'}</strong>
        </div>
        <div className="nfc-worker-stat">
          <span>启动时间</span>
          <strong>{formatDateTime(data?.started_at)}</strong>
        </div>
        <div className="nfc-worker-stat">
          <span>最近心跳</span>
          <strong>{formatDateTime(data?.heartbeat_at)}</strong>
        </div>
        <div className="nfc-worker-stat">
          <span>延迟</span>
          <strong>{formatHeartbeatAge(data?.heartbeat_age_seconds)}</strong>
        </div>
      </div>
    </section>
  );
};
