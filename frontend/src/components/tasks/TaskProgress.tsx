import React from 'react';
import { Progress, Typography, Space, Spin } from 'antd';
import { TaskProgress as TaskProgressType, TaskStatus } from '../../types/task';
import { computeProgressPercentage } from './task_utils';

const { Text } = Typography;

interface Props {
  progress: TaskProgressType;
  status?: TaskStatus | string;
  size?: 'small' | 'default';
  showDetails?: boolean;
}

export const TaskProgress: React.FC<Props> = ({
  progress,
  status,
  size = 'small',
  showDetails = false,
}) => {
  const current = progress?.current || 0;
  const total = progress?.total || 0;
  const message = progress?.message;
  const percent = computeProgressPercentage(current, total, progress?.percent);

  // Case 1: Known total > 0, we can show a legitimate percentage progress bar
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
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2, flexWrap: 'wrap' }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {current} / {total} {showDetails ? ` (${percent}%)` : ''}
          </Text>
          {message && (
            <Text
              type="secondary"
              ellipsis={{ tooltip: message }}
              style={{ fontSize: 11, maxWidth: showDetails ? 200 : 120, marginLeft: 8 }}
            >
              {message}
            </Text>
          )}
        </div>
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
        <Text type="secondary" style={{ fontSize: 11 }}>
          进度未知{current > 0 ? ` (已处理 ${current} 项)` : ''}
        </Text>
      </Space>
    );
  }

  if (status === 'completed') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="success" style={{ fontSize: 12 }}>
          已完成{current > 0 ? ` (${current} 项)` : ''}
        </Text>
        {message && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {message}
          </Text>
        )}
      </Space>
    );
  }

  if (status === 'failed') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="danger" style={{ fontSize: 12 }}>
          已失败{current > 0 ? ` (已处理 ${current} 项)` : ''}
        </Text>
        {message && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {message}
          </Text>
        )}
      </Space>
    );
  }

  if (status === 'cancelled') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          已取消{current > 0 ? ` (已处理 ${current} 项)` : ''}
        </Text>
        {message && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {message}
          </Text>
        )}
      </Space>
    );
  }

  if (status === 'paused') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="warning" style={{ fontSize: 12 }}>
          已暂停{current > 0 ? ` (进度已保存: ${current} 项)` : ''}
        </Text>
        {message && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {message}
          </Text>
        )}
      </Space>
    );
  }

  if (status === 'cancel_requested') {
    return (
      <Space direction="vertical" size={1}>
        <Text type="warning" style={{ fontSize: 12 }}>
          正在取消...{current > 0 ? ` (${current} 项)` : ''}
        </Text>
        {message && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {message}
          </Text>
        )}
      </Space>
    );
  }

  // Queued or default
  return (
    <Space direction="vertical" size={1}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {message || '等待 Worker 执行...'}
      </Text>
      {current > 0 && (
        <Text type="secondary" style={{ fontSize: 11 }}>
          已处理 {current} 项
        </Text>
      )}
    </Space>
  );
};
