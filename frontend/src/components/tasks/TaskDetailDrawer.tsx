import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';

import { TaskProgress } from './TaskProgress';
import { TaskLogTable } from './TaskLogTable';
import { TaskActionBar } from './TaskActionBar';
import { TaskDeleteButton } from './TaskDeleteButton';
import { MediaPackageRecoveryPanel } from './MediaPackageRecoveryPanel';
import { ConsoleButton } from '../ui/ConsoleButton';
import { CodePath } from '../ui/CodePath';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { StatusBadge } from '../ui/StatusBadge';

import { tasksApi } from '../../api/tasks';
import { formatDateTime, formatElapsed } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { sqliteIdText } from '../../utils/sqliteId';
import { taskTypeLabel } from '../../utils/taskTypeLabel';
import { taskSourceLink } from './taskRecordLinks';
import { getTaskDeleteAvailability } from './task_cleanup';
import { getReportedTaskSpeed } from './task_utils';
import type { TaskDetail, TaskId } from '../../types/task';

const LONG_ERROR_THRESHOLD = 240;
const ERROR_PREVIEW_CHARS = 160;

interface Props {
  taskId: TaskId | null;
  open: boolean;
  onClose: () => void;
  onViewTask?: (taskId: TaskId) => void;
  returnFocusFallback?: () => HTMLElement | null;
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

/** Keep the one-second clock local to the running task's progress and duration. */
function TaskRunOverview({ task, open }: { task: TaskDetail; open: boolean }) {
  const running = task.status === 'running' || task.status === 'cancel_requested';
  const live = open && running && Boolean(task.started_at) && !task.finished_at;
  const [currentTime, setCurrentTime] = useState(dayjs);
  useEffect(() => {
    if (!live) return;
    setCurrentTime(dayjs());
    const timer = setInterval(() => setCurrentTime(dayjs()), 1000);
    return () => clearInterval(timer);
  }, [live]);

  const elapsed = task.finished_at || running ? formatElapsed(task.started_at, task.finished_at, currentTime) : null;
  return (
    <section className="nfc-overlay-section nfc-v2-task-overview">
      <header className="nfc-overlay-section-header">
        <h3>执行进度</h3>
        {elapsed && elapsed !== '-' && (
          <div className="nfc-v2-task-run-duration"><span>耗时</span><strong>{elapsed}</strong></div>
        )}
      </header>
      <TaskProgress progress={task.progress} status={task.status} reportedSpeed={getReportedTaskSpeed(task)}
        startedAt={task.started_at} now={currentTime} summarized />
    </section>
  );
}

/** Scroll only the drawer's content and put the log region in the keyboard reading order. */
function revealTaskLogs(target: HTMLElement | null) {
  const sheetBody = target?.closest<HTMLElement>('.nfc-v2-sheet-body');
  if (!target || !sheetBody) return;
  target.focus({ preventScroll: true });
  const top = sheetBody.scrollTop + target.getBoundingClientRect().top - sheetBody.getBoundingClientRect().top - 12;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  sheetBody.scrollTo({ top, behavior: reducedMotion ? 'instant' : 'smooth' });
}

export const TaskDetailDrawer: React.FC<Props> = ({ taskId, open, onClose, onViewTask, returnFocusFallback }) => {
  const logs = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const lastTaskId = useRef<TaskId | null>(null);
  useLayoutEffect(() => {
    if (taskId !== null) lastTaskId.current = taskId;
  }, [taskId]);
  // Keep the last details visible during the exit without continuing to poll.
  const visibleTaskId = taskId ?? lastTaskId.current;
  const { data: task, isLoading, isError, error, isFetching, refetch } = useQuery({
    queryKey: ['taskDetail', visibleTaskId === null ? null : String(visibleTaskId)],
    queryFn: () => (visibleTaskId ? tasksApi.getTaskDetail(visibleTaskId) : Promise.reject('No ID')),
    enabled: Boolean(taskId && open),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const isActive = status === 'queued' || status === 'running' || status === 'cancel_requested';
      return isActive ? 3000 : false;
    },
  });
  useLayoutEffect(() => {
    if (!open) return;
    content.current?.closest<HTMLElement>('.nfc-v2-sheet-body')?.scrollTo({ top: 0, behavior: 'instant' });
  }, [open, task?.id]);

  const sourceLink = task && taskSourceLink(task);
  const originalTaskId = sqliteIdText(task?.retry_of);
  const cloudCopy = task?.job_type === 'cloud-copy' ? task : undefined;
  const remoteDirectory = cloudCopy?.payload?.remote_root;
  const importedDirectory = cloudCopy?.payload?.local_root;
  const pendingDirectory = cloudCopy?.payload?.staging_path;
  const organizerDirectory = task?.job_type === 'media-organizer-preview' || task?.job_type === 'media-organizer-batch'
    ? task.payload?.selection : undefined;
  const taskPath = importedDirectory ?? organizerDirectory;

  return (
    <ConsoleSheet open={open} onClose={onClose}
      title="任务详情"
      returnFocusFallback={returnFocusFallback}
      description={task ? taskTypeLabel(task.job_type) : undefined}
      className="nfc-task-detail-drawer nfc-reading-sheet"
      titleAside={task ? (
        <><span className="nfc-v2-task-id">#{task.id}</span><StatusBadge status={task.status} /></>
      ) : visibleTaskId ? <span className="nfc-v2-task-id">#{visibleTaskId}</span> : null}
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
        <div ref={content} className="nfc-overlay-stack nfc-v2-task-inspector">
          {(task.error || task.error_code) && (
            <div className="nfc-v2-task-inline-alert nfc-overlay-alert" role="alert">
              <strong>{task.error_code ? '错误 [' + task.error_code + ']' : '任务执行失败 / 异常'}</strong>
              {task.error && (task.error.length > LONG_ERROR_THRESHOLD ? (
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
              ) : <p className="nfc-prewrap-error">{task.error}</p>)}
            </div>
          )}

          <TaskRunOverview key={task.id} task={task} open={open} />

          <section className="nfc-overlay-section nfc-v2-task-commands">
            <header className="nfc-overlay-section-header">
              <div><h3>任务操作</h3></div>
            </header>
            <TaskActionBar key={task.id} task={task} onViewTask={onViewTask} />
            <div className="nfc-task-evidence-links">
              {sourceLink && <Link className="nfc-task-origin-link" to={sourceLink.href}>{sourceLink.label}</Link>}
              {cloudCopy?.status === 'completed' && typeof importedDirectory === 'string' && (
                <Link className="nfc-task-origin-link"
                  to={'/batch?' + new URLSearchParams({ operation: 'media-organize', directory: importedDirectory })}>
                  预览整理
                </Link>
              )}
              {originalTaskId && (onViewTask ? (
                <button type="button" className="nfc-task-origin-link"
                  onClick={() => onViewTask(originalTaskId)}>原任务 #{originalTaskId}</button>
              ) : <span>原任务 #{originalTaskId}</span>)}
              <button type="button" className="nfc-task-origin-link" onClick={() => revealTaskLogs(logs.current)}>
                查看任务日志
              </button>
              {getTaskDeleteAvailability(task).enabled &&
                !(task.job_type === 'media_package-package-execute' && task.status === 'failed') && (
                  <TaskDeleteButton key={task.id} task={task} size="small" type="default"
                    danger onSuccess={onClose} />
                )}
            </div>
          </section>

          {typeof taskPath === 'string' && taskPath && (
            <section className="nfc-overlay-section">
              <header className="nfc-overlay-section-header"><h3>任务路径</h3></header>
              <dl className="nfc-v2-task-facts nfc-v2-task-paths">
                {typeof remoteDirectory === 'string' && remoteDirectory && (
                  <div className="is-wide"><dt>云端来源</dt><dd><CodePath value={remoteDirectory} /></dd></div>
                )}
                <div className="is-wide"><dt>{cloudCopy ? 'NAS 目标目录' : '整理目录'}</dt>
                  <dd><CodePath value={taskPath} /></dd>
                </div>
                {cloudCopy && cloudCopy.status !== 'completed' && typeof pendingDirectory === 'string' && pendingDirectory && (
                  <div className="is-wide"><dt>暂存路径</dt><dd><CodePath value={pendingDirectory} /></dd></div>
                )}
              </dl>
            </section>
          )}

          <section className="nfc-overlay-section">
            <header className="nfc-overlay-section-header">
              <div><h3>运行时间</h3></div>
            </header>
            <dl className="nfc-v2-task-facts">
              <div><dt>创建</dt><dd>{formatDateTime(task.created_at)}</dd></div>
              <div><dt>开始</dt><dd>{formatDateTime(task.started_at)}</dd></div>
              <div><dt>结束</dt><dd>{formatDateTime(task.finished_at)}</dd></div>
              <div><dt>最近心跳</dt><dd>{formatDateTime(task.heartbeat_at)}</dd></div>
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
