import React from 'react';
import { Card, Badge, Typography, Space, Skeleton, Alert, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { formatDateTime, formatHeartbeatAge } from '../../utils/format';
import { WORKER_STATUS_BADGE_MAP } from './task_utils';

const { Text } = Typography;

export const WorkerStatusCard: React.FC = () => {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['workerStatus'],
    queryFn: () => tasksApi.getWorkerStatus(),
    refetchInterval: 5000,
    retry: 1,
  });

  if (isError) {
    return (
      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Alert
          type="warning"
          showIcon
          message="Worker 状态暂不可用"
          description={
            typeof error === 'object' && error && 'message' in error
              ? String(error.message)
              : '无法连接到后台 Worker 状态服务，任务列表仍可正常查看。'
          }
          style={{ borderRadius: 8 }}
        />
      </Card>
    );
  }

  if (isLoading && !data) {
    return (
      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Skeleton active paragraph={{ rows: 1 }} />
      </Card>
    );
  }

  const workerStatus = data?.status || 'offline';
  const badgeConfig = WORKER_STATUS_BADGE_MAP[workerStatus] || WORKER_STATUS_BADGE_MAP.offline;

  return (
    <Card
      bordered={false}
      style={{
        borderRadius: 12,
        marginBottom: 16,
        background: 'linear-gradient(180deg, #ffffff 0%, #fafafa 100%)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}
      bodyStyle={{ padding: '16px 20px' }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 16,
        }}
      >
        <Space size={12} align="center">
          <Text strong style={{ fontSize: 15 }}>
            调度 Worker
          </Text>
          <Tag color={badgeConfig.color} style={{ margin: 0, padding: '2px 8px' }}>
            <Badge status={badgeConfig.badgeStatus} text={badgeConfig.label} />
          </Tag>
        </Space>

        <Space size={24} wrap align="center">
          <div>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
              Worker ID:
            </Text>
            <Text code style={{ fontSize: 12 }}>
              {data?.worker_id || '-'}
            </Text>
          </div>

          <div>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
              启动时间:
            </Text>
            <Text style={{ fontSize: 12 }}>
              {formatDateTime(data?.started_at)}
            </Text>
          </div>

          <div>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
              最近心跳:
            </Text>
            <Text style={{ fontSize: 12 }}>
              {formatDateTime(data?.heartbeat_at)}
            </Text>
          </div>

          <div>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
              心跳延迟:
            </Text>
            <Text strong style={{ fontSize: 12 }}>
              {formatHeartbeatAge(data?.heartbeat_age_seconds)}
            </Text>
          </div>
        </Space>
      </div>
    </Card>
  );
};
