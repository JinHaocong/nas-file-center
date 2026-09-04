import React from 'react';
import { Progress, Typography, Space, Spin } from 'antd';
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

  // Case 1: Known total > 0, we can show a legitimate percentage progress bar with ETA
  if (total > 0 && percent !== null) {
    let progressStatus: 'success' | 'exception' | 'normal' | 'active' | undefined = undefined;
    if (status === 'failed') {
      progressStatus = 'exception';
    } else if (status === 'completed') {
      progressStatus = 'success';
    } else if (status === 'running') {
      progressStatus = 'active';
    }

    return (
      <div style={{ minWidth: 140 }}>
        <Progress
          percent={percent}
          size={size}
          status={progressStatus}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2, flexWrap: 'wrap', gap: '2px 8px' }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {current} / {total} {showDetails ? ` (${percent}%)` : ''}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
        </div>
        {message && (
          <Text
            type="secondary"
            ellipsis={{ tooltip: message }}
            style={{ fontSize: 11, maxWidth: showDetails ? 240 : 160, marginTop: 2, display: 'block' }}
          >
            {message}
          </Text>
        )}
      </div>
    );
  }

  // Case 2: Total is 0 or unknown. Strictly DO NOT fabricate percentage (0% or 50% or 99%).
  if (status === 'running') {
    return (
      <Space direction="vertical" size={1} style={{ minWidth: 140 }}>
        <Space size={6} align="center">
          <Spin size="small" />
          <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: message || '正在执行...' }}>
            {message || '正在执行...'}
          </Text>
        </Space>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            进度未知{current > 0 ? ` (${current} 项)` : ''}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
        </div>
      </Space>
    );
  }

  if (status === 'completed') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="success" style={{ fontSize: 12 }}>
          已完成{current > 0 ? ` (${current} 项)` : ''}
        </Text>
        <div style={{ display: 'flex', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
          {message && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              · {message}
            </Text>
          )}
        </div>
      </Space>
    );
  }

  if (status === 'failed') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="danger" style={{ fontSize: 12 }}>
          已失败{current > 0 ? ` (${current} 项)` : ''}
        </Text>
        <div style={{ display: 'flex', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
          {message && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              · {message}
            </Text>
          )}
        </div>
      </Space>
    );
  }

  if (status === 'cancelled') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          已取消{current > 0 ? ` (${current} 项)` : ''}
        </Text>
        <div style={{ display: 'flex', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
          {message && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              · {message}
            </Text>
          )}
        </div>
      </Space>
    );
  }

  if (status === 'paused') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="warning" style={{ fontSize: 12 }}>
          已暂停{current > 0 ? ` (已处理: ${current} 项)` : ''}
        </Text>
        <div style={{ display: 'flex', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
          {message && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              · {message}
            </Text>
          )}
        </div>
      </Space>
    );
  }

  if (status === 'cancel_requested') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="warning" style={{ fontSize: 12 }}>
          正在取消...{current > 0 ? ` (${current} 项)` : ''}
        </Text>
        <div style={{ display: 'flex', gap: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            ETA: {eta.text}
          </Text>
          {message && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              · {message}
            </Text>
          )}
        </div>
      </Space>
    );
  }

  // Queued or default
  return (
    <Space direction="vertical" size={1}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {message || '等待 Worker 执行...'}
      </Text>
      <div style={{ display: 'flex', gap: 8 }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          ETA: {eta.text}
        </Text>
        {current > 0 && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            · 已处理 {current} 项
          </Text>
        )}
      </div>
    </Space>
  );
};
