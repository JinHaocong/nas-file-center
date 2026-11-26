import { taskSourceLink } from './taskRecordLinks';
import { sqliteIdText } from '../../utils/sqliteId';
import { taskTypeLabel } from '../../utils/taskTypeLabel';
import React, { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { tasksApi } from '../../api/tasks';
import { TaskProgress } from './TaskProgress';
import { TaskLogTable } from './TaskLogTable';
import { formatDateTime, formatElapsed } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { getTaskDeleteAvailability } from './task_cleanup';
import { TaskActionBar } from './TaskActionBar';
import { TaskDeleteButton } from './TaskDeleteButton';
import { MediaPackageRecoveryPanel } from './MediaPackageRecoveryPanel';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { StatusBadge } from '../ui/StatusBadge';
import type { TaskId } from '../../types/task';

const LONG_ERROR_THRESHOLD = 240;
const ERROR_PREVIEW_CHARS = 160;

interface Props {
  taskId: TaskId | null;
  open: boolean;
  onClose: () => void;
  onViewTask?: (taskId: TaskId) => void;
}

const ContextDetails: React.FC<{
  title: string;
  data: Record<string, unknown> | null | undefined;
  emptyLabel: string;
}> = ({ title, data, emptyLabel }) => (
  data && Object.keys(data).length > 0 ? (
    <details className="nfc-v2-task-context">
      <summary>{title}</summary>
      <pre className="nfc-code-block" tabIndex={0} aria-label={title}>
        {JSON.stringify(sanitizeContext(data), null, 2)}
      </pre>
    </details>
  ) : (
    <div className="nfc-v2-task-context nfc-reading-empty-context">
      <strong>{title}</strong><span className="nfc-v2-task-muted">{emptyLabel}</span>
    </div>
  )
);

export const TaskDetailDrawer: React.FC<Props> = ({ taskId, open, onClose, onViewTask }) => {
  const logs = useRef<HTMLElement>(null);
  const { data: task, isLoading, isError, error, isFetching, refetch } = useQuery({
    queryKey: ['taskDetail', taskId === null ? null : String(taskId)],
    queryFn: () => (taskId ? tasksApi.getTaskDetail(taskId) : Promise.reject('No ID')),
    enabled: Boolean(taskId && open),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const isActive = status === 'queued' || status === 'running' || status === 'cancel_requested';
      return isActive ? 3000 : false;
    },
  });

  const sourceLink = task && taskSourceLink(task);
  const originalTaskId = sqliteIdText(task?.retry_of);

  return (
    <ConsoleSheet open={open} onClose={onClose}
      title="任务详情"
      description={task ? taskTypeLabel(task.job_type) : undefined}
      className="nfc-task-detail-drawer nfc-reading-sheet"
      titleAside={task ? (
        <><span className="nfc-v2-task-id">#{task.id}</span><StatusBadge status={task.status} /></>
      ) : taskId ? <span className="nfc-v2-task-id">#{taskId}</span> : null}
    >
      {isLoading && <div className="nfc-overlay-loading" role="status">正在加载任务详情…</div>}
      {isError && (
        <div className="nfc-v2-task-inline-alert" role="alert">
          <strong>加载任务详情失败</strong>
          <p>{error instanceof Error ? error.message : '网络请求异常'}</p>
          <ConsoleButton size="sm" onClick={() => { void refetch(); }} loading={isFetching}>重试</ConsoleButton>
        </div>
      )}
      {!isError && task && (
        <div className="nfc-overlay-stack nfc-v2-task-inspector">
          {task.error && (
            <div className="nfc-v2-task-inline-alert nfc-overlay-alert" role="alert">
              <strong>{task.error_code ? '错误 [' + task.error_code + ']' : '任务执行失败 / 异常'}</strong>
              {task.error.length > LONG_ERROR_THRESHOLD ? (
                <>
                  <p className="nfc-prewrap-error nfc-v2-task-error-preview">
                    {task.error.slice(0, ERROR_PREVIEW_CHARS)}…
                  </p>
                  <details className="nfc-v2-task-error-details">
                    <summary>
                      <span className="nfc-v2-task-error-expand">展开完整错误信息</span>
                      <span className="nfc-v2-task-error-collapse">收起完整错误信息</span>
                    </summary>
                    <p className="nfc-prewrap-error">{task.error}</p>
                  </details>
                </>
              ) : <p className="nfc-prewrap-error">{task.error}</p>}
            </div>
          )}

          <section className="nfc-overlay-section nfc-v2-task-overview">
            <header className="nfc-overlay-section-header">
              <div><h3>执行进度</h3></div>
            </header>
            <TaskProgress progress={task.progress} status={task.status}
              startedAt={task.started_at} summarized />
          </section>

          <section className="nfc-overlay-section nfc-v2-task-commands">
            <header className="nfc-overlay-section-header">
              <div><h3>任务操作</h3></div>
            </header>
            <TaskActionBar key={task.id} task={task} onViewTask={onViewTask} />
            <div className="nfc-task-evidence-links">
              {sourceLink && <Link className="nfc-task-origin-link" to={sourceLink.href}>{sourceLink.label}</Link>}
              {originalTaskId && (onViewTask ? (
                <button type="button" className="nfc-task-origin-link"
                  onClick={() => onViewTask(originalTaskId)}>原任务 #{originalTaskId}</button>
              ) : <span>原任务 #{originalTaskId}</span>)}
              <button type="button" className="nfc-task-origin-link" onClick={() => {
                logs.current?.focus({ preventScroll: true });
                logs.current?.scrollIntoView({ block: 'start' });
              }}>查看任务日志</button>
              {getTaskDeleteAvailability(task).enabled &&
                !(task.job_type === 'media_package-package-execute' && task.status === 'failed') && (
                  <TaskDeleteButton key={task.id} task={task} size="small" type="default"
                    danger onSuccess={onClose} />
                )}
            </div>
          </section>

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div><h3>运行时间</h3></div>
            </header>
            <dl className="nfc-v2-task-facts">
              <div><dt>创建</dt><dd>{formatDateTime(task.created_at)}</dd></div>
              <div><dt>开始</dt><dd>{formatDateTime(task.started_at)}</dd></div>
              <div><dt>结束</dt><dd>{formatDateTime(task.finished_at)}</dd></div>
              <div><dt>最近心跳</dt><dd>{formatDateTime(task.heartbeat_at)}</dd></div>
              <div><dt>总耗时</dt><dd><strong>{formatElapsed(task.started_at, task.finished_at)}</strong></dd></div>
            </dl>
          </section>

          {task.job_type === 'media_package-package-execute' &&
            typeof task.id === 'number' &&
            task.status === 'failed' &&
            task.error_code === 'EXECUTION_ERROR' &&
            (task.error === 'Package directory changed before publish' ||
              task.error?.startsWith('[Errno 95] Plain directory rename no-clobber semantics are not positively proven: ')) && (
              <MediaPackageRecoveryPanel key={task.id} failedJobId={task.id}
                onViewTask={onViewTask} />
            )}

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div><h3>执行上下文</h3></div>
            </header>
            <div className="nfc-v2-task-context-stack">
              <ContextDetails title="断点恢复快照" data={task.checkpoint} emptyLabel="无断点数据" />
              <ContextDetails title="任务参数状态" data={task.payload} emptyLabel="无参数状态数据" />
            </div>
          </section>

          <section ref={logs} tabIndex={-1} aria-label="任务日志" className="nfc-overlay-section nfc-overlay-section-flush nfc-task-log-target">
            <TaskLogTable key={task.id} taskId={task.id} />
          </section>
        </div>
      )}
    </ConsoleSheet>
  );
};
