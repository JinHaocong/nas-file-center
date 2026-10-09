import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TaskProgress } from './TaskProgress';
import { TaskLogTable } from './TaskLogTable';
import { formatDateTime, formatElapsed } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { calculateTaskEta } from './task_utils';
import { TaskActionBar } from './TaskActionBar';
import { TaskDeleteButton } from './TaskDeleteButton';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { StatusBadge } from '../ui/StatusBadge';

interface Props {
  taskId: number | null;
  open: boolean;
  onClose: () => void;
  onViewTask?: (taskId: number) => void;
}

const ContextDetails: React.FC<{
  title: string;
  data: Record<string, unknown> | null | undefined;
  emptyLabel: string;
}> = ({ title, data, emptyLabel }) => (
  <details className="nfc-v2-task-context">
    <summary>{title}</summary>
    {data && Object.keys(data).length > 0
      ? <pre className="nfc-code-block">{JSON.stringify(sanitizeContext(data), null, 2)}</pre>
      : <span className="nfc-v2-task-muted">{emptyLabel}</span>}
  </details>
);

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

  const caps = task?.capabilities || {
    supports_pause: false,
    supports_resume: false,
    supports_cancel: false,
    supports_retry: false,
  };

  const capabilityBadges = (
    <div className="nfc-v2-task-capabilities">
      {([
        ['暂停', caps.supports_pause],
        ['恢复', caps.supports_resume],
        ['取消', caps.supports_cancel],
        ['重试', caps.supports_retry],
      ] as const).map(([label, supported]) => (
        <span key={label} className={'nfc-v2-task-capability' + (supported ? ' is-supported' : '')}>
          {label} {supported ? '支持' : '不支持'}
        </span>
      ))}
    </div>
  );

  return (
    <ConsoleSheet open={open} onClose={onClose}
      title="任务详情" eyebrow="Task inspector"
      description="查看 Worker 任务执行记录、恢复上下文与关联事件日志。"
      className="nfc-task-detail-drawer"
      titleAside={task ? (
        <><span className="nfc-v2-task-id">#{task.id}</span><StatusBadge status={task.status} /></>
      ) : taskId ? <span className="nfc-v2-task-id">#{taskId}</span> : null}
    >
      {isLoading && <div className="nfc-overlay-loading" role="status">正在加载任务详情…</div>}
      {isError && (
        <div className="nfc-v2-task-inline-alert" role="alert">
          <strong>加载任务详情失败</strong>
          <p>{error instanceof Error ? error.message : '网络请求异常'}</p>
        </div>
      )}
      {!isError && task && (
        <div className="nfc-overlay-stack nfc-v2-task-inspector">
          {task.error && (
            <div className="nfc-v2-task-inline-alert nfc-overlay-alert" role="alert">
              <strong>{task.error_code ? '错误 [' + task.error_code + ']' : '任务执行失败 / 异常'}</strong>
              <p className="nfc-prewrap-error">{task.error}</p>
            </div>
          )}

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div><span>Execution</span><h3>执行状态</h3></div>
            </header>
            <dl className="nfc-v2-task-facts">
              <div><dt>任务 ID</dt><dd><strong>#{task.id}</strong></dd></div>
              <div><dt>任务类型</dt><dd><span className="nfc-kind-badge">{task.job_type}</span></dd></div>
              <div><dt>当前状态</dt><dd><StatusBadge status={task.status} /></dd></div>
              <div><dt>原始任务</dt><dd>{task.retry_of ? <strong>#{task.retry_of}</strong> : '—'}</dd></div>
              <div className="is-wide"><dt>任务能力</dt><dd>{capabilityBadges}</dd></div>
              <div className="is-wide"><dt>执行进度</dt><dd>
                <TaskProgress progress={task.progress} status={task.status}
                  startedAt={task.started_at} showDetails />
              </dd></div>
            </dl>
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div><span>Timeline</span><h3>运行时间</h3></div>
            </header>
            <dl className="nfc-v2-task-facts">
              <div><dt>创建</dt><dd>{formatDateTime(task.created_at)}</dd></div>
              <div><dt>开始</dt><dd>{formatDateTime(task.started_at)}</dd></div>
              <div><dt>结束</dt><dd>{formatDateTime(task.finished_at)}</dd></div>
              <div><dt>最近心跳</dt><dd>{formatDateTime(task.heartbeat_at)}</dd></div>
              <div><dt>总耗时</dt><dd><strong>{formatElapsed(task.started_at, task.finished_at)}</strong></dd></div>
              <div><dt>预计剩余</dt><dd><strong>
                {calculateTaskEta(
                  task.status,
                  task.progress?.current,
                  task.progress?.total,
                  task.started_at,
                  task.progress?.percent,
                ).text}
              </strong></dd></div>
            </dl>
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header nfc-overlay-section-header-actions">
              <div><span>Controls</span><h3>任务操作</h3></div>
              <TaskDeleteButton task={task} size="small" type="default"
                danger onSuccess={onClose} />
            </header>
            <TaskActionBar task={task} onViewTask={onViewTask} />
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div><span>Recovery</span><h3>执行上下文</h3></div>
            </header>
            <div className="nfc-v2-task-context-stack">
              <ContextDetails title="断点恢复快照" data={task.checkpoint} emptyLabel="无断点数据" />
              <ContextDetails title="任务参数状态" data={task.payload} emptyLabel="无参数状态数据" />
            </div>
          </section>

          <section className="nfc-overlay-section nfc-overlay-section-flush">
            <TaskLogTable key={task.id} taskId={task.id} />
          </section>
        </div>
      )}
    </ConsoleSheet>
  );
};
