import React from 'react';
import {
  Alert,
  Collapse,
  Descriptions,
  Drawer,
  Space,
  Spin,
  Tag,
  Typography,
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
import { TaskDeleteButton } from './TaskDeleteButton';

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
    if (!task) return '—';
    const caps = task.capabilities || {
      supports_pause: false,
      supports_resume: false,
      supports_cancel: false,
      supports_retry: false,
    };
    return (
      <Space wrap size={[6, 6]}>
        <Tag color={caps.supports_pause ? 'green' : 'default'}>暂停 {caps.supports_pause ? '支持' : '不支持'}</Tag>
        <Tag color={caps.supports_resume ? 'green' : 'default'}>恢复 {caps.supports_resume ? '支持' : '不支持'}</Tag>
        <Tag color={caps.supports_cancel ? 'green' : 'default'}>取消 {caps.supports_cancel ? '支持' : '不支持'}</Tag>
        <Tag color={caps.supports_retry ? 'green' : 'default'}>重试 {caps.supports_retry ? '支持' : '不支持'}</Tag>
      </Space>
    );
  };

  const renderJsonBlock = (
    data: Record<string, unknown> | null | undefined,
    emptyLabel: string,
  ) => {
    if (!data || Object.keys(data).length === 0) {
      return <Text type="secondary">{emptyLabel}</Text>;
    }
    return (
      <pre className="nfc-code-block">
        {JSON.stringify(sanitizeContext(data), null, 2)}
      </pre>
    );
  };

  return (
    <Drawer
      rootClassName="nfc-overlay-drawer nfc-task-detail-drawer"
      title={
        <div className="nfc-drawer-title">
          <span className="nfc-drawer-title-kicker">Task inspector</span>
          <div className="nfc-drawer-title-row">
            <span>任务详情</span>
            {task && <Text code>#{task.id}</Text>}
            {task && <TaskStatusTag status={task.status} />}
          </div>
        </div>
      }
      placement="right"
      width={760}
      onClose={onClose}
      open={open}
      destroyOnClose
    >
      {isLoading && (
        <div className="nfc-overlay-loading">
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
        <div className="nfc-overlay-stack">
          {task.error && (
            <Alert
              className="nfc-overlay-alert"
              type="error"
              showIcon
              message={task.error_code ? `错误 [${task.error_code}]` : '任务执行失败 / 异常'}
              description={
                <div className="nfc-prewrap-error">
                  {task.error}
                </div>
              }
            />
          )}

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div>
                <span>Execution</span>
                <h3>执行状态</h3>
              </div>
            </header>
            <Descriptions
              className="nfc-detail-descriptions"
              size="small"
              column={{ xxl: 2, xl: 2, lg: 2, md: 1, sm: 1, xs: 1 }}
            >
              <Descriptions.Item label="任务 ID">
                <Text strong>#{task.id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="任务类型">
                <Tag>{task.job_type}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="当前状态">
                <TaskStatusTag status={task.status} />
              </Descriptions.Item>
              <Descriptions.Item label="原始任务">
                {task.retry_of ? <Text strong>#{task.retry_of}</Text> : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="任务能力" span={2}>
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
            </Descriptions>
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div>
                <span>Timeline</span>
                <h3>运行时间</h3>
              </div>
            </header>
            <Descriptions
              className="nfc-detail-descriptions"
              size="small"
              column={{ xxl: 2, xl: 2, lg: 2, md: 1, sm: 1, xs: 1 }}
            >
              <Descriptions.Item label="创建">{formatDateTime(task.created_at)}</Descriptions.Item>
              <Descriptions.Item label="开始">{formatDateTime(task.started_at)}</Descriptions.Item>
              <Descriptions.Item label="结束">{formatDateTime(task.finished_at)}</Descriptions.Item>
              <Descriptions.Item label="最近心跳">{formatDateTime(task.heartbeat_at)}</Descriptions.Item>
              <Descriptions.Item label="总耗时">
                <Text strong>{formatElapsed(task.started_at, task.finished_at)}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="预计剩余">
                <Text strong>
                  {calculateTaskEta(
                    task.status,
                    task.progress?.current,
                    task.progress?.total,
                    task.started_at,
                    task.progress?.percent,
                  ).text}
                </Text>
              </Descriptions.Item>
            </Descriptions>
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header nfc-overlay-section-header-actions">
              <div>
                <span>Controls</span>
                <h3>任务操作</h3>
              </div>
              <TaskDeleteButton
                task={task}
                size="small"
                type="default"
                danger
                onSuccess={onClose}
              />
            </header>
            <TaskActionBar task={task} onViewTask={onViewTask} />
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div>
                <span>Recovery</span>
                <h3>执行上下文</h3>
              </div>
            </header>
            <Collapse
              className="nfc-detail-collapse"
              size="small"
              items={[
                {
                  key: 'checkpoint',
                  label: '断点恢复快照',
                  children: renderJsonBlock(task.checkpoint, '无断点数据'),
                },
                {
                  key: 'payload',
                  label: '任务参数状态',
                  children: renderJsonBlock(task.payload, '无参数状态数据'),
                },
              ]}
            />
          </section>

          <section className="nfc-overlay-section nfc-overlay-section-flush">
            <TaskLogTable taskId={task.id} />
          </section>
        </div>
      )}
    </Drawer>
  );
};
