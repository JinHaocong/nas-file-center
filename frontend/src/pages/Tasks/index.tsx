import React, { useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { WorkerStatusCard } from '../../components/tasks/WorkerStatusCard';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { TaskDetailDrawer } from '../../components/tasks/TaskDetailDrawer';
import { TaskDeleteButton } from '../../components/tasks/TaskDeleteButton';
import { TaskHistoryCleanupModal } from '../../components/tasks/TaskHistoryCleanupModal';
import { OrganizerReportInventory } from '../../components/tasks/OrganizerReportInventory';
import { TaskRowCommand, TaskRowFeedback,
  getTaskRowActionFailure, getTaskRowCommand } from '../../components/tasks/TaskRowFeedback';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleSelect } from '../../components/ui/ConsoleSelect';
import { ConsoleIcon, type ConsoleIconName } from '../../components/ui/ConsoleIcon';

import { tasksApi } from '../../api/tasks';
import { useAuth } from '../../contexts/AuthContext';
import { fileWorkspaceReturn } from '../../components/layout/navItems';
import { getReportedTaskSpeed } from '../../components/tasks/task_utils';
import { getTaskDeleteAvailability } from '../../components/tasks/task_cleanup';
import { useTaskRowActions } from '../../components/tasks/useTaskRowActions';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { sqliteIdText } from '../../utils/sqliteId';
import { taskTypeLabel } from '../../utils/taskTypeLabel';

import type { TaskId, TaskItem } from '../../types/task';

const STATUS_OPTIONS = [
  { label: '全部状态', value: 'all' },
  { label: '排队中 (queued)', value: 'queued' },
  { label: '执行中 (running)', value: 'running' },
  { label: '已暂停 (paused)', value: 'paused' },
  { label: '取消中 (cancel_requested)', value: 'cancel_requested' },
  { label: '已取消 (cancelled)', value: 'cancelled' },
  { label: '已失败 (failed)', value: 'failed' },
  { label: '已完成 (completed)', value: 'completed' },
];

const JOB_TYPE_OPTIONS = [
  { label: '全部类型', value: 'all' },
  { label: '媒体整理', value: 'media-organizer-batch' },
  { label: taskTypeLabel('fclones-scan'), value: 'fclones-scan' },
  { label: taskTypeLabel('index-root'), value: 'index-root' },
  { label: taskTypeLabel('workflow-scheduled'), value: 'workflow-scheduled' },
  { label: taskTypeLabel('workflow-quick-run'), value: 'workflow-quick-run' },
  { label: taskTypeLabel('media-analysis'), value: 'media-analysis' },
  { label: taskTypeLabel('media-integrity-verify'), value: 'media-integrity-verify' },
  { label: taskTypeLabel('download-verify-webdav'), value: 'download-verify-webdav' },
  { label: taskTypeLabel('cloud-copy'), value: 'cloud-copy' },
];

const QUICK_STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '进行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '异常', value: 'failed' },
] as const;

const TASK_ICONS: Record<string, ConsoleIconName> = {
  'media-analysis': 'file-search', 'media-integrity-verify': 'file-check', 'media-organizer-batch': 'layers',
  'media-organizer-preview': 'folder-open', 'fclones-scan': 'search', 'index-root': 'database',
  'workflow-quick-run': 'workflow', 'workflow-scheduled': 'workflow', 'cloud-copy': 'cloud',
};

/** Return focus to the queue if the detail was opened by a link or its launcher is gone. */
function taskQueueFocusTarget() {
  return document.getElementById('nfc-task-queue');
}

/** Keep filters and maintenance accessible without competing with refresh or task search. */
function TaskToolbarMore({ children, filtered }: { children: React.ReactNode; filtered: boolean }) {
  const [open, setOpen] = useState(false);
  const options = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: Event) => {
      if (!(event.target instanceof Node) || options.current?.contains(event.target) ||
          document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
      setOpen(false);
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('focusin', closeOutside);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('focusin', closeOutside);
    };
  }, [open]);

  return <div ref={options} className="nfc-task-toolbar-more" onKeyDown={event => {
    if (event.key !== 'Escape' || !open || !event.currentTarget.contains(event.target as Node)) return;
    event.preventDefault();
    event.stopPropagation();
    setOpen(false);
    trigger.current?.focus({ preventScroll: true });
  }}>
    <ConsoleButton ref={trigger} size="sm" className="nfc-task-toolbar-trigger" data-filtered={filtered || undefined}
      aria-label="任务筛选与更多操作" title="任务筛选与更多操作" aria-expanded={open} aria-controls={panelId}
      leadingIcon={<ConsoleIcon name="ellipsis" size={17} />} onClick={() => setOpen(current => !current)} />
    <div id={panelId} className="nfc-task-toolbar-popover" role="group" aria-label="任务筛选与更多操作"
      hidden={!open}>{children}</div>
  </div>;
}

/** Render the same record identity and detail trigger in the table and on mobile. */
function TaskRecordIdentity({ task, selected, onOpen }: {
  task: TaskItem;
  selected: boolean;
  onOpen: (taskId: TaskId, trigger: HTMLButtonElement) => void;
}) {
  return (
    <div className="nfc-v2-task-identity">
      <span className="nfc-task-row-icon"><ConsoleIcon name={TASK_ICONS[task.job_type] ?? 'list-checks'} size={17} /></span>
      <div className="nfc-task-row-name">
        <strong>{taskTypeLabel(task.job_type)}</strong>
        <div className="nfc-v2-task-identity-meta">
          <button type="button" className="nfc-table-link nfc-mono nfc-v2-task-id"
            aria-haspopup="dialog" aria-expanded={selected}
            onClick={event => onOpen(task.id, event.currentTarget)}>#{task.id}</button>
          {(task.error || task.error_code) && (
            <span className="nfc-table-error nfc-v2-task-error">{task.error_code || '有错误记录'}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export const TasksPage: React.FC = () => {
  useTitle('任务中心');
  const { user } = useAuth();
  const showOrganizerResult = user?.role === 'admin';
  const { feedbackById, dispatch } = useTaskRowActions();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [statusFilter, setStatusFilter] = useState('all');
  const [jobTypeFilter, setJobTypeFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const selectedTaskId = sqliteIdText(searchParams.get('task'));
  const returnToFiles = fileWorkspaceReturn(location.state);

  /** Put drawer selection in the URL so reload and browser Back restore the shown record. */
  function openTaskDetail(taskId: TaskId, trigger?: HTMLButtonElement) {
    const nextId = sqliteIdText(taskId);
    if (!nextId || nextId === selectedTaskId) return;
    // WebKit does not focus mouse-activated buttons by default. Let the
    // shared drawer capture the exact opener just like keyboard activation.
    trigger?.focus({ preventScroll: true });
    const next = new URLSearchParams(searchParams);
    next.set('task', nextId);
    setSearchParams(next, {
      replace: selectedTaskId !== null,
      state: { fileWorkspaceReturn: returnToFiles, taskFromList: selectedTaskId === null || location.state?.taskFromList === true },
    });
  }

  /** A deep link closes into the list; an in-list opener returns to its history entry. */
  function closeTaskDetail() {
    if (location.state?.taskFromList === true) {
      navigate(-1);
      return;
    }
    if (searchParams.has('task')) {
      const next = new URLSearchParams(searchParams);
      next.delete('task');
      setSearchParams(next, { replace: true, state: { fileWorkspaceReturn: returnToFiles } });
    }
  }

  const { data, isLoading, isError, error, refetch, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['tasksList', page, pageSize, statusFilter, jobTypeFilter],
    queryFn: () =>
      tasksApi.listTasks({
        page,
        pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter,
        jobType: jobTypeFilter === 'all' ? undefined : jobTypeFilter,
      }),
    // Keep same-filter pagination mounted without keeping operations from the previous page visible.
    placeholderData: (previous, previousQuery) => previous && previousQuery?.queryKey[3] === statusFilter &&
      previousQuery.queryKey[4] === jobTypeFilter
      ? { items: [], total: previous.total, page, page_size: pageSize } : undefined,
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some(
        (j) => j.status === 'queued' || j.status === 'running' || j.status === 'cancel_requested'
      );
      return hasActive ? 3000 : false;
    },
  });

  const handleStatusFilterChange = (val: string) => {
    setStatusFilter(val);
    setPage(1);
  };

  const handleJobTypeFilterChange = (val: string) => {
    setJobTypeFilter(val);
    setPage(1);
  };

  const changePage = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };

  const handleDeleted = (taskId: TaskId) => {
    if (page > 1 && data?.items?.length === 1) {
      setPage((prev) => Math.max(1, prev - 1));
    }
    if (selectedTaskId !== null && String(selectedTaskId) === String(taskId)) {
      closeTaskDetail();
    }
  };

  const isFiltered = statusFilter !== 'all' || jobTypeFilter !== 'all';
  const items: TaskItem[] = isError ? [] : data?.items || [];
  const searchTerm = search.trim().toLocaleLowerCase();
  const matching = searchTerm ? items.filter(task => [taskTypeLabel(task.job_type), task.job_type, `#${task.id}`]
    .some(value => value.toLocaleLowerCase().includes(searchTerm))) : items;
  const noItemsTitle = searchTerm ? '当前页没有匹配的任务' : isFiltered ? '没有匹配的任务' : '暂无任务记录';
  const noItemsDescription = searchTerm ? '请调整关键词或切换页码。' : isFiltered
    ? '请尝试切换状态或类型。' : '扫描、索引或执行计划生成的任务会显示在这里。';

  const pagination = !isError && !isLoading && (data?.total || 0) > 0 && (
    <ConsolePagination
      page={page}
      pageSize={pageSize}
      total={data?.total || 0}
      pageSizes={[20, 50, 100, 200]}
      onChange={changePage}
    />
  );

  const rows = matching.map(task => {
    const id = sqliteIdText(task.id);
    const selected = selectedTaskId !== null && id === selectedTaskId;
    const feedback = id ? feedbackById[id] : undefined;
    const rowProps = { task, feedback, onAction: (item: TaskItem, action: 'pause' | 'resume') => { void dispatch(item, action); } };
    const hasFeedback = Boolean(getTaskRowActionFailure(task, feedback) ||
      (showOrganizerResult && task.job_type === 'media-organizer-batch' && task.status === 'completed' && task.organizer_result));
    const timestamp = task.finished_at ?? task.heartbeat_at ?? task.started_at ?? task.created_at;
    const updated = formatDateTime(timestamp);
    return {
      task, selected, className: selected ? ' nfc-record-selected' : '',
      updated: timestamp ? <time dateTime={timestamp} title={updated}>{updated.slice(5, 16)}</time> : '—',
      identity: <TaskRecordIdentity task={task} selected={selected} onOpen={openTaskDetail} />,
      status: <StatusBadge status={task.status} label={task.status === 'running' ? '进行中' : undefined} />,
      progress: <TaskProgress progress={task.progress} status={task.status} compact
        reportedSpeed={getReportedTaskSpeed(task)} />,
      command: getTaskRowCommand(task, feedback) ? <TaskRowCommand {...rowProps} /> : null,
      feedback: hasFeedback ? <TaskRowFeedback {...rowProps} showOrganizerResult={showOrganizerResult} /> : null,
    };
  });

  return (
    <div className="nfc-operations-page nfc-tasks-page nfc-page-layout-ledger nfc-v2-tasks-page nfc-record-workspace">
      <PageHeader title="任务中心" actions={<ConsoleButton loading={isFetching}
        leadingIcon={<ConsoleIcon name="refresh" size={16} />} onClick={() => refetch()}>刷新</ConsoleButton>} />

      {isError && (
        <div className="nfc-v2-task-alert nfc-page-alert" role="alert">
          <ConsoleIcon name="x" size={19} />
          <div>
            <strong>任务列表加载失败</strong>
            <p>{error instanceof Error ? error.message : '无法连接到任务服务，请检查 NAS 服务端状态'}</p>
          </div>
          <ConsoleButton size="sm" onClick={() => refetch()}>重试</ConsoleButton>
        </div>
      )}

      <DataPanel
        id="nfc-task-queue"
        title="任务队列"
        action={<span className="nfc-panel-count">{isError ? '—' : data?.total ?? 0} 项</span>}
        className="nfc-panel-flush nfc-task-queue-panel"
        variant="dense"
      >
        <ActionBar className="nfc-filter-bar nfc-v2-task-filter-bar">
          <div className="nfc-record-segments" role="group" aria-label="任务快捷筛选">
            {QUICK_STATUS_OPTIONS.map(({ label, value }) => (
              <button key={value} type="button" aria-pressed={statusFilter === value}
                onClick={() => handleStatusFilterChange(value)}>{label}</button>
            ))}
          </div>
          <div className="nfc-task-queue-tools">
            <div className="nfc-task-search-box" title="按名称或编号搜索当前页任务">
              <ConsoleIcon name="search" size={15} />
              <input type="search" aria-label="搜索当前页任务" placeholder="搜索任务"
                value={search} onChange={event => setSearch(event.currentTarget.value)} />
            </div>
            <TaskToolbarMore filtered={isFiltered}>
              <div className="nfc-task-toolbar-filters">
                <ConsoleSelect id="nfc-task-status-filter" label="状态" value={statusFilter}
                  onChange={handleStatusFilterChange} options={STATUS_OPTIONS} />
                <ConsoleSelect id="nfc-task-type-filter" label="任务类型" value={jobTypeFilter}
                  onChange={handleJobTypeFilterChange} options={JOB_TYPE_OPTIONS} />
                {isFiltered && <ConsoleButton variant="ghost" size="sm" onClick={() => {
                  setStatusFilter('all');
                  setJobTypeFilter('all');
                  setPage(1);
                }} leadingIcon={<ConsoleIcon name="x" size={15} />}>清除筛选</ConsoleButton>}
              </div>
              <div className="nfc-task-toolbar-actions">
                {returnToFiles && <Link className="nfc-console-button nfc-console-button-secondary nfc-console-button-sm"
                  to={returnToFiles} state={{ restoreFileWorkspace: true }}>
                  <ConsoleIcon name="arrow-left" size={16} />返回文件空间
                </Link>}
                {showOrganizerResult && <OrganizerReportInventory />}
                <TaskHistoryCleanupModal onCleaned={() => { setPage(1); closeTaskDetail(); }} />
                <details className="nfc-task-worker-details">
                  <summary><ConsoleIcon name="activity" size={15} />调度 Worker 状态</summary>
                  <WorkerStatusCard />
                </details>
              </div>
            </TaskToolbarMore>
          </div>
        </ActionBar>

        {isError ? (
          <ConsoleEmpty title="暂时无法显示任务" description="请先恢复任务服务连接，已有任务不会受到影响。" />
        ) : isLoading || isPlaceholderData ? (
          <div className="nfc-v2-task-loading" role="status">正在加载任务列表…</div>
        ) : matching.length === 0 ? (
          <ConsoleEmpty title={noItemsTitle} description={noItemsDescription} />
        ) : (
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-task-table-scroll">
                <table className="nfc-v2-task-table">
                  <thead><tr>
                    <th scope="col">任务</th>
                    <th scope="col">状态</th>
                    <th scope="col">进度</th>
                    <th scope="col" className="nfc-task-updated">更新时间</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{rows.map(row => {
                    const { task, selected } = row;
                    return (<React.Fragment key={task.id}>
                      <tr data-task-row={String(task.id)} className={'nfc-task-list-row' + row.className}>
                        <td>{row.identity}</td>
                        <td>{row.status}</td>
                        <td className="nfc-v2-task-progress-cell">
                          {row.progress}
                        </td>
                        <td className="nfc-task-updated">{row.updated}</td>
                        <td><div className="nfc-row-actions">
                          {row.command ?? <ConsoleButton size="sm" variant="secondary" aria-haspopup="dialog" aria-expanded={selected}
                            leadingIcon={<ConsoleIcon name="search" size={15} />}
                            onClick={event => openTaskDetail(task.id, event.currentTarget)}>任务详情</ConsoleButton>}
                          {getTaskDeleteAvailability(task).enabled && <TaskDeleteButton task={task} size="small" type="text" iconOnly
                            onSuccess={() => handleDeleted(task.id)} />}
                        </div></td>
                      </tr>
                      {row.feedback && <tr className="nfc-task-list-feedback-row"><td colSpan={5}>{row.feedback}</td></tr>}
                    </React.Fragment>);
                  })}</tbody>
                </table>
              </div>
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {rows.map(row => {
                  const { task, selected } = row;
                  return (
                    <article className={'nfc-task-mobile-card' + row.className} data-task-row={String(task.id)} key={task.id}>
                      <div className="nfc-mobile-record-heading">
                        {row.identity}
                        {row.status}
                      </div>
                      <div className="nfc-mobile-record-progress">
                        {row.progress}
                      </div>
                      {row.feedback}
                      <div className="nfc-mobile-record-actions">
                        {row.command}
                        <ConsoleButton size="sm" variant="ghost" aria-haspopup="dialog" aria-expanded={selected}
                          leadingIcon={<ConsoleIcon name="search" size={15} />}
                          onClick={event => openTaskDetail(task.id, event.currentTarget)}>查看详情</ConsoleButton>
                        {getTaskDeleteAvailability(task).enabled && <TaskDeleteButton task={task} size="small" type="text" iconOnly
                          onSuccess={() => handleDeleted(task.id)} />}
                      </div>
                    </article>
                  );
                })}
              </div>
            }
          />
        )}
        {searchTerm && !isPlaceholderData && !isLoading && !isError && (
          <div className="nfc-task-search-count" role="status">本页匹配 {matching.length} 项</div>
        )}
        {pagination}
      </DataPanel>

      <TaskDetailDrawer
        taskId={selectedTaskId}
        open={selectedTaskId !== null}
        listActionPending={Boolean(selectedTaskId && feedbackById[selectedTaskId]?.phase === 'pending')}
        onClose={closeTaskDetail}
        onViewTask={openTaskDetail}
        returnToFiles={returnToFiles}
        returnFocusFallback={taskQueueFocusTarget}
      />
    </div>
  );
};
