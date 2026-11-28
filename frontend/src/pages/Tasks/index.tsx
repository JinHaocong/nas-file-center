import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { tasksApi } from '../../api/tasks';
import { useTitle } from '../../hooks/useTitle';
import { sqliteIdText } from '../../utils/sqliteId';
import { taskTypeLabel } from '../../utils/taskTypeLabel';
import type { TaskId, TaskItem } from '../../types/task';
import { WorkerStatusCard } from '../../components/tasks/WorkerStatusCard';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { TaskDetailDrawer } from '../../components/tasks/TaskDetailDrawer';
import { TaskDeleteButton } from '../../components/tasks/TaskDeleteButton';
import { TaskHistoryCleanupModal } from '../../components/tasks/TaskHistoryCleanupModal';
import { OrganizerReportInventory } from '../../components/tasks/OrganizerReportInventory';
import { getReportedTaskSpeed } from '../../components/tasks/task_utils';
import { fileWorkspaceReturn } from '../../components/layout/navItems';
import { useAuth } from '../../contexts/AuthContext';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleSelect } from '../../components/ui/ConsoleSelect';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';

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
  { label: taskTypeLabel('media-analysis'), value: 'media-analysis' },
  { label: taskTypeLabel('media-integrity-verify'), value: 'media-integrity-verify' },
  { label: taskTypeLabel('download-verify-webdav'), value: 'download-verify-webdav' },
  { label: taskTypeLabel('cloud-copy'), value: 'cloud-copy' },
];

const QUICK_STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '执行中', value: 'running' },
  { label: '已失败', value: 'failed' },
] as const;

/** Return focus to the queue if the detail was opened by a link or its launcher is gone. */
function taskQueueFocusTarget() {
  return document.getElementById('nfc-task-queue');
}

/** Render the same record identity and detail trigger in the table and on mobile. */
function TaskRecordIdentity({ task, selected, onOpen }: {
  task: TaskItem;
  selected: boolean;
  onOpen: (taskId: TaskId, trigger: HTMLButtonElement) => void;
}) {
  return (
    <div className="nfc-v2-task-identity">
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
  );
}

export const TasksPage: React.FC = () => {
  useTitle('任务中心');
  const { user } = useAuth();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [statusFilter, setStatusFilter] = useState('all');
  const [jobTypeFilter, setJobTypeFilter] = useState('all');
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
  const latestFailure = !isFiltered && items.find(task => task.status === 'failed');
  const noItemsTitle = isFiltered ? '没有匹配的任务' : '暂无任务记录';
  const noItemsDescription = isFiltered
    ? '当前筛选条件没有找到记录，请尝试切换状态或类型。'
    : '扫描、索引或执行计划生成的任务会显示在这里。';

  const pagination = !isError && !isLoading && (data?.total || 0) > 0 && (
    <ConsolePagination
      page={page}
      pageSize={pageSize}
      total={data?.total || 0}
      pageSizes={[20, 50, 100, 200]}
      onChange={changePage}
    />
  );

  return (
    <div className="nfc-operations-page nfc-tasks-page nfc-page-layout-ledger nfc-v2-tasks-page nfc-record-workspace">
      <PageHeader
        title="任务中心"
        actions={
          <ActionBar compact>
            {returnToFiles && <Link className="nfc-console-button nfc-console-button-secondary nfc-console-button-sm"
              to={returnToFiles} state={{ restoreFileWorkspace: true }}>
              <ConsoleIcon name="arrow-left" size={16} />返回文件空间
            </Link>}
            {user?.role === 'admin' && <OrganizerReportInventory />}
            <TaskHistoryCleanupModal
              onCleaned={() => {
                setPage(1);
                closeTaskDetail();
              }}
            />
            <ConsoleButton
              loading={isFetching}
              leadingIcon={<ConsoleIcon name="refresh" size={16} />}
              onClick={() => refetch()}
            >刷新</ConsoleButton>
          </ActionBar>
        }
      />

      <WorkerStatusCard />

      {latestFailure && (
        <section className="nfc-record-attention" aria-label="本页最近失败的任务">
          <ConsoleIcon name="info" size={18} />
          <div><strong>本页最近失败 · #{latestFailure.id} {taskTypeLabel(latestFailure.job_type)}</strong></div>
          <ConsoleButton size="sm" onClick={event => openTaskDetail(latestFailure.id, event.currentTarget)}>查看失败详情</ConsoleButton>
        </section>
      )}

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
        className="nfc-panel-flush"
        variant="dense"
      >
        <ActionBar className="nfc-filter-bar nfc-v2-task-filter-bar">
          <div className="nfc-record-segments" role="group" aria-label="任务快捷筛选">
            {QUICK_STATUS_OPTIONS.map(({ label, value }) => (
              <button key={value} type="button" aria-pressed={statusFilter === value}
                onClick={() => handleStatusFilterChange(value)}>{label}</button>
            ))}
          </div>
          <ConsoleSelect id="nfc-task-status-filter" label="状态" value={statusFilter}
            onChange={handleStatusFilterChange} options={STATUS_OPTIONS} />
          <ConsoleSelect id="nfc-task-type-filter" label="任务类型" value={jobTypeFilter}
            onChange={handleJobTypeFilterChange} options={JOB_TYPE_OPTIONS} />
          {isFiltered && (
            <ConsoleButton variant="ghost" size="sm" onClick={() => {
              setStatusFilter('all');
              setJobTypeFilter('all');
              setPage(1);
            }} leadingIcon={<ConsoleIcon name="x" size={15} />}>清除筛选</ConsoleButton>
          )}
          <span className="nfc-v2-task-filter-hint">
            <ConsoleIcon name="activity" size={15} /> 活动任务自动更新
          </span>
        </ActionBar>

        {isError ? (
          <ConsoleEmpty title="暂时无法显示任务" description="请先恢复任务服务连接，已有任务不会受到影响。" />
        ) : isLoading || isPlaceholderData ? (
          <div className="nfc-v2-task-loading" role="status">正在加载任务列表…</div>
        ) : items.length === 0 ? (
          <ConsoleEmpty title={noItemsTitle} description={noItemsDescription} />
        ) : (
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-task-table-scroll">
                <table className="nfc-v2-task-table">
                  <thead><tr>
                    <th scope="col">任务</th>
                    <th scope="col">状态</th>
                    <th scope="col">执行进度</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(task => {
                    const selected = selectedTaskId !== null && sqliteIdText(task.id) === selectedTaskId;
                    return (
                      <tr key={task.id} className={selected ? 'nfc-record-selected' : undefined}>
                        <td><TaskRecordIdentity task={task} selected={selected} onOpen={openTaskDetail} /></td>
                        <td><StatusBadge status={task.status} /></td>
                        <td className="nfc-v2-task-progress-cell">
                          <TaskProgress progress={task.progress} status={task.status} compact
                            reportedSpeed={getReportedTaskSpeed(task)} />
                        </td>
                        <td><div className="nfc-row-actions">
                          <ConsoleButton size="sm" variant="ghost" aria-haspopup="dialog" aria-expanded={selected}
                            leadingIcon={<ConsoleIcon name="search" size={15} />}
                            onClick={event => openTaskDetail(task.id, event.currentTarget)}>详情</ConsoleButton>
                          <TaskDeleteButton task={task} size="small" type="text"
                            onSuccess={() => handleDeleted(task.id)} />
                        </div></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {items.map(task => {
                  const selected = selectedTaskId !== null && sqliteIdText(task.id) === selectedTaskId;
                  return (
                    <article className={'nfc-task-mobile-card' + (selected ? ' nfc-record-selected' : '')} key={task.id}>
                      <div className="nfc-mobile-record-heading">
                        <TaskRecordIdentity task={task} selected={selected} onOpen={openTaskDetail} />
                        <StatusBadge status={task.status} />
                      </div>
                      <div className="nfc-mobile-record-progress">
                        <TaskProgress progress={task.progress} status={task.status} compact
                          reportedSpeed={getReportedTaskSpeed(task)} />
                      </div>
                      <div className="nfc-mobile-record-actions">
                        <ConsoleButton size="sm" variant="ghost" aria-haspopup="dialog" aria-expanded={selected}
                          leadingIcon={<ConsoleIcon name="search" size={15} />}
                          onClick={event => openTaskDetail(task.id, event.currentTarget)}>查看详情</ConsoleButton>
                        <TaskDeleteButton task={task} type="text"
                          onSuccess={() => handleDeleted(task.id)} />
                      </div>
                    </article>
                  );
                })}
              </div>
            }
          />
        )}
        {pagination}
      </DataPanel>

      <TaskDetailDrawer
        taskId={selectedTaskId}
        open={selectedTaskId !== null}
        onClose={closeTaskDetail}
        onViewTask={openTaskDetail}
        returnToFiles={returnToFiles}
        returnFocusFallback={taskQueueFocusTarget}
      />
    </div>
  );
};
