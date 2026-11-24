import { sqliteIdText } from '../../utils/sqliteId';
import { taskTypeLabel } from '../../utils/taskTypeLabel';
import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { tasksApi } from '../../api/tasks';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime, formatElapsed } from '../../utils/format';
import type { TaskId, TaskItem } from '../../types/task';
import { WorkerStatusCard } from '../../components/tasks/WorkerStatusCard';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { TaskDetailDrawer } from '../../components/tasks/TaskDetailDrawer';
import { TaskDeleteButton } from '../../components/tasks/TaskDeleteButton';
import { TaskHistoryCleanupModal } from '../../components/tasks/TaskHistoryCleanupModal';
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
];

export const TasksPage: React.FC = () => {
  useTitle('任务中心');

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [statusFilter, setStatusFilter] = useState('all');
  const [jobTypeFilter, setJobTypeFilter] = useState('all');
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const selectedTaskId = sqliteIdText(searchParams.get('task'));
  const [currentTime, setCurrentTime] = useState<dayjs.Dayjs>(() => dayjs());

  /** Put drawer selection in the URL so reload and browser Back restore the shown record. */
  function openTaskDetail(taskId: TaskId) {
    const nextId = sqliteIdText(taskId);
    if (!nextId || nextId === selectedTaskId) return;
    const next = new URLSearchParams(searchParams);
    next.set('task', nextId);
    setSearchParams(next, {
      replace: selectedTaskId !== null,
      state: { taskFromList: selectedTaskId === null || location.state?.taskFromList === true },
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
      setSearchParams(next, { replace: true });
    }
  }

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['tasksList', page, pageSize, statusFilter, jobTypeFilter],
    queryFn: () =>
      tasksApi.listTasks({
        page,
        pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter,
        jobType: jobTypeFilter === 'all' ? undefined : jobTypeFilter,
      }),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some(
        (j) => j.status === 'queued' || j.status === 'running' || j.status === 'cancel_requested'
      );
      return hasActive ? 3000 : false;
    },
  });

  useEffect(() => {
    const hasRunning = data?.items?.some((j) => j.status === 'running');
    if (!hasRunning) return;
    const timer = setInterval(() => {
      setCurrentTime(dayjs());
    }, 1000);
    return () => clearInterval(timer);
  }, [data?.items]);

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
    <div className="nfc-operations-page nfc-tasks-page nfc-page-layout-ledger nfc-v2-tasks-page">
      <PageHeader
        title="任务中心"
        description="查看正在进行的任务，打开记录可核对进度和执行结果。"
        actions={
          <ActionBar compact>
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
        title="任务队列"
        description="按状态和类型筛选任务。"
        action={<span className="nfc-panel-count">{isError ? '—' : data?.total ?? 0} 项</span>}
        className="nfc-panel-flush"
        variant="dense"
      >
        <ActionBar className="nfc-filter-bar nfc-v2-task-filter-bar">
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
        ) : isLoading ? (
          <div className="nfc-v2-task-loading" role="status">正在加载任务列表…</div>
        ) : items.length === 0 ? (
          <ConsoleEmpty title={noItemsTitle} description={noItemsDescription} />
        ) : (
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-task-table-scroll">
                <table className="nfc-v2-task-table">
                  <thead><tr>
                    <th scope="col">任务 ID</th>
                    <th scope="col">任务类型</th>
                    <th scope="col">状态</th>
                    <th scope="col">执行进度</th>
                    <th scope="col">创建时间</th>
                    <th scope="col">执行耗时</th>
                    <th scope="col">错误</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(task => {
                    const errorText = task.error || task.error_code || '';
                    const clippedError = errorText.length > 28 ? errorText.slice(0, 28) + '…' : errorText;
                    return (
                      <tr key={task.id}>
                        <td>
                          <button type="button" className="nfc-table-link nfc-mono nfc-v2-task-id"
                            onClick={() => openTaskDetail(task.id)}>
                            #{task.id}
                          </button>
                        </td>
                        <td><span className="nfc-kind-badge" title={task.job_type}>{taskTypeLabel(task.job_type)}</span></td>
                        <td><StatusBadge status={task.status} /></td>
                        <td className="nfc-v2-task-progress-cell">
                          <TaskProgress progress={task.progress} status={task.status}
                            startedAt={task.started_at} now={currentTime} />
                        </td>
                        <td className="nfc-v2-task-date">{formatDateTime(task.created_at)}</td>
                        <td className="nfc-v2-task-date">
                          {formatElapsed(task.started_at, task.finished_at, currentTime)}
                        </td>
                        <td>
                          {errorText ? (
                            <span className="nfc-table-error nfc-v2-task-error" title={errorText}>
                              {task.error_code ? '[' + task.error_code + '] ' : ''}{clippedError}
                            </span>
                          ) : <span className="nfc-table-muted">—</span>}
                        </td>
                        <td><div className="nfc-row-actions">
                          <ConsoleButton size="sm" variant="ghost"
                            leadingIcon={<ConsoleIcon name="search" size={15} />}
                            onClick={() => openTaskDetail(task.id)}>详情</ConsoleButton>
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
                {items.map(task => (
                  <article className="nfc-task-mobile-card" key={task.id}>
                    <div className="nfc-mobile-record-heading">
                      <div>
                        <button type="button" className="nfc-mobile-record-title nfc-mono"
                          onClick={() => openTaskDetail(task.id)}>#{task.id}</button>
                        <span className="nfc-kind-badge" title={task.job_type}>{taskTypeLabel(task.job_type)}</span>
                      </div>
                      <StatusBadge status={task.status} />
                    </div>
                    <div className="nfc-mobile-record-progress">
                      <TaskProgress progress={task.progress} status={task.status}
                        startedAt={task.started_at} now={currentTime} showDetails />
                    </div>
                    <div className="nfc-mobile-record-facts">
                      <span>创建 <b>{formatDateTime(task.created_at)}</b></span>
                      <span>耗时 <b>{formatElapsed(task.started_at, task.finished_at, currentTime)}</b></span>
                    </div>
                    {(task.error || task.error_code) && (
                      <div className="nfc-mobile-record-error">
                        {task.error_code ? '[' + task.error_code + '] ' : ''}
                        {task.error || task.error_code}
                      </div>
                    )}
                    <div className="nfc-mobile-record-actions">
                      <ConsoleButton size="sm" variant="ghost"
                        leadingIcon={<ConsoleIcon name="search" size={15} />}
                        onClick={() => openTaskDetail(task.id)}>查看详情</ConsoleButton>
                      <TaskDeleteButton task={task} type="text"
                        onSuccess={() => handleDeleted(task.id)} />
                    </div>
                  </article>
                ))}
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
      />
    </div>
  );
};
