import React from 'react';
import {
  Drawer,
  Descriptions,
  Tag,
  Typography,
  Alert,
  Divider,
  Collapse,
  Spin,
  Space,
} from 'antd';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TaskStatusTag } from './TaskStatusTag';
import { TaskProgress } from './TaskProgress';
import { TaskLogTable } from './TaskLogTable';
import { formatDateTime, formatElapsed } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { calculateTaskEta } from './task_utils';
import { TaskActionBar } from './TaskActionBar';

const { Text } = Typography;

interface Props {
  taskId: number | null;
  open: boolean;
  onClose: () => void;
  onViewTask?: (taskId: number) => void;
}

export const TaskDetailDrawer: React.FC<Props> = ({ taskId, open, onClose, onViewTask }) => {
  const { data: task, isLoading, isError, error } = useQuery({
    queryKey: ['taskDetail', taskId],
    queryFn: () => (taskId ? tasksApi.getTaskDetail(taskId) : Promise.reject('No ID')),
    enabled: Boolean(taskId && open),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const isActive = status === 'queued' || status === 'running' || status === 'cancel_requested';
      return isActive ? 3000 : false;
    },
  });

  const renderCapabilities = () => {
    if (!task) return '-';
    const caps = task.capabilities || {
      supports_pause: false,
      supports_resume: false,
      supports_cancel: false,
      supports_retry: false,
    };

    return (
      <Space wrap size={[6, 6]}>
        <Tag color={caps.supports_pause ? 'green' : 'default'}>
          暂停: {caps.supports_pause ? '支持' : '不支持'}
        </Tag>
        <Tag color={caps.supports_resume ? 'green' : 'default'}>
          恢复: {caps.supports_resume ? '支持' : '不支持'}
        </Tag>
        <Tag color={caps.supports_cancel ? 'green' : 'default'}>
          取消: {caps.supports_cancel ? '支持' : '不支持'}
        </Tag>
        <Tag color={caps.supports_retry ? 'green' : 'default'}>
          重试: {caps.supports_retry ? '支持' : '不支持'}
        </Tag>
      </Space>
    );
  };

  const renderJsonBlock = (data: Record<string, unknown> | null | undefined, emptyLabel: string) => {
    if (!data || Object.keys(data).length === 0) {
      return <Text type="secondary">{emptyLabel}</Text>;
    }
    const sanitized = sanitizeContext(data);
    return (
      <pre
        style={{
          margin: 0,
          padding: '8px 12px',
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 6,
          fontSize: 12,
          maxHeight: 220,
          overflow: 'auto',
        }}
      >
        {JSON.stringify(sanitized, null, 2)}
      </pre>
    );
  };

  return (
    <Drawer
      title={
        <Space>
          <span>任务详情</span>
          {task && <Text code>#{task.id}</Text>}
          {task && <TaskStatusTag status={task.status} />}
        </Space>
      }
      placement="right"
      width={720}
      onClose={onClose}
      open={open}
      destroyOnClose
    >
      {isLoading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin tip="正在加载任务详情..." />
        </div>
      )}

      {isError && (
        <Alert
          type="error"
          showIcon
          message="加载任务详情失败"
          description={error instanceof Error ? error.message : '网络请求异常'}
        />
      )}

      {task && (
        <div>
          {task.error && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 16 }}
              message={
                task.error_code ? `错误 [${task.error_code}]` : '任务执行失败 / 异常'
              }
              description={
                <div style={{ wordBreak: 'break-word', whiteSpace: 'pre-wrap', marginTop: 4 }}>
                  {task.error}
                </div>
              }
            />
          )}

          <Descriptions
            bordered
            size="small"
            column={{ xxl: 2, xl: 2, lg: 2, md: 1, sm: 1, xs: 1 }}
          >
            <Descriptions.Item label="任务 ID">
              <Text strong>#{task.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="任务类型">
              <Tag color="blue">{task.job_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="当前状态">
              <TaskStatusTag status={task.status} />
            </Descriptions.Item>
            <Descriptions.Item label="原始任务 (Retry Of)">
              {task.retry_of ? <Text strong>#{task.retry_of}</Text> : '-'}
            </Descriptions.Item>

            <Descriptions.Item label="任务能力 (Capabilities)" span={2}>
              {renderCapabilities()}
            </Descriptions.Item>

            <Descriptions.Item label="执行进度" span={2}>
              <TaskProgress
                progress={task.progress}
                status={task.status}
                startedAt={task.started_at}
                showDetails
              />
            </Descriptions.Item>

            <Descriptions.Item label="创建时间">
              {formatDateTime(task.created_at)}
            </Descriptions.Item>
            <Descriptions.Item label="开始执行时间">
              {formatDateTime(task.started_at)}
            </Descriptions.Item>
            <Descriptions.Item label="结束完成时间">
              {formatDateTime(task.finished_at)}
            </Descriptions.Item>
            <Descriptions.Item label="最近心跳时间">
              {formatDateTime(task.heartbeat_at)}
            </Descriptions.Item>
            <Descriptions.Item label="总执行耗时">
              <Text strong>{formatElapsed(task.started_at, task.finished_at)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="预计剩余 (ETA)">
              <Text strong>
                {
                  calculateTaskEta(
                    task.status,
                    task.progress?.current,
                    task.progress?.total,
                    task.started_at,
                    task.progress?.percent
                  ).text
                }
              </Text>
            </Descriptions.Item>
          </Descriptions>

          <Divider style={{ margin: '16px 0' }} />

          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 13, color: '#475569' }}>
              任务操作 (Task Actions)
            </Text>
            <TaskActionBar task={task} onViewTask={onViewTask} />
          </div>

          <Divider style={{ margin: '16px 0' }} />

          <Collapse
            size="small"
            items={[
              {
                key: 'checkpoint',
                label: '断点恢复快照 (Checkpoint Data)',
                children: renderJsonBlock(task.checkpoint, '无断点数据'),
              },
              {
                key: 'payload',
                label: '任务参数状态 (Payload / State Data)',
                children: renderJsonBlock(task.payload, '无参数状态数据'),
              },
            ]}
            style={{ marginBottom: 16 }}
          />

          <Divider style={{ margin: '16px 0' }} />

          {/* Embedded Task Logs */}
          <TaskLogTable taskId={task.id} />
        </div>
      )}
    </Drawer>
  );
};
