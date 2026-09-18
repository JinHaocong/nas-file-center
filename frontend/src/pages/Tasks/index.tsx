import React, { useState, useEffect } from 'react';
import {
  Alert,
  Button,
  Empty,
  Pagination,
  Select,
  Table,
  Tooltip,
} from 'antd';
import { EyeOutlined, ReloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { tasksApi } from '../../api/tasks';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime, formatElapsed } from '../../utils/format';
import { TaskItem, TaskStatus } from '../../types/task';
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
  { label: 'fclones-scan', value: 'fclones-scan' },
  { label: 'index-root', value: 'index-root' },
];

export const TasksPage: React.FC = () => {
  useTitle('任务中心');

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [jobTypeFilter, setJobTypeFilter] = useState<string>('all');
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState<dayjs.Dayjs>(() => dayjs());

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

  const handleDeleted = (taskId: number) => {
    if (page > 1 && data?.items?.length === 1) {
      setPage((prev) => Math.max(1, prev - 1));
    }
    if (selectedTaskId === taskId) {
      setSelectedTaskId(null);
    }
  };

  const isFiltered = statusFilter !== 'all' || jobTypeFilter !== 'all';
  const items = data?.items || [];

  const columns = [
    {
      title: '任务 ID',
      dataIndex: 'id',
      key: 'id',
      width: 88,
      render: (id: number) => (
        <button type="button" className="nfc-table-link nfc-mono" onClick={() => setSelectedTaskId(id)}>
          #{id}
        </button>
      ),
    },
    {
      title: '任务类型',
      dataIndex: 'job_type',
      key: 'job_type',
      width: 138,
      render: (type: string) => <span className="nfc-kind-badge">{type}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 118,
      render: (status: TaskStatus) => <StatusBadge status={status} />,
    },
    {
      title: '进度',
      key: 'progress',
      width: 230,
      render: (_: unknown, record: TaskItem) => (
        <TaskProgress
          progress={record.progress}
          status={record.status}
          startedAt={record.started_at}
          now={currentTime}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 158,
      render: (val: string | null) => <span className="nfc-table-meta">{formatDateTime(val)}</span>,
    },
    {
      title: '执行耗时',
      key: 'elapsed',
      width: 108,
      render: (_: unknown, record: TaskItem) => (
        <span className="nfc-table-meta">{formatElapsed(record.started_at, record.finished_at, currentTime)}</span>
      ),
    },
    {
      title: '错误',
      key: 'error',
      width: 190,
      render: (_: unknown, record: TaskItem) => {
        if (!record.error && !record.error_code) return <span className="nfc-table-muted">—</span>;
        const fullErr = record.error || record.error_code || '';
        const displayErr = fullErr.length > 28 ? `${fullErr.slice(0, 28)}…` : fullErr;
        return (
          <Tooltip title={fullErr}>
            <span className="nfc-table-error">
              {record.error_code ? `[${record.error_code}] ` : ''}
              {displayErr}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 142,
      fixed: 'right' as const,
      render: (_: unknown, record: TaskItem) => (
        <div className="nfc-row-actions">
          <Button
            size="small"
            type="text"
            icon={<EyeOutlined />}
            onClick={() => setSelectedTaskId(record.id)}
          >
            详情
          </Button>
          <TaskDeleteButton
            task={record}
            size="small"
            type="text"
            onSuccess={() => handleDeleted(record.id)}
          />
        </div>
      ),
    },
  ];

  const mobileCards = (
    <div className="nfc-mobile-record-list">
      {items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={isFiltered ? '无匹配任务 (No matching tasks)' : '暂无任务 (No tasks yet)'}
        />
      ) : (
        items.map((task) => (
          <article className="nfc-task-mobile-card" key={task.id}>
            <div className="nfc-mobile-record-heading">
              <div>
                <button
                  type="button"
                  className="nfc-mobile-record-title nfc-mono"
                  onClick={() => setSelectedTaskId(task.id)}
                >
                  #{task.id}
                </button>
                <span className="nfc-kind-badge">{task.job_type}</span>
              </div>
              <StatusBadge status={task.status} />
            </div>

            <div className="nfc-mobile-record-progress">
              <TaskProgress
                progress={task.progress}
                status={task.status}
                startedAt={task.started_at}
                now={currentTime}
                showDetails
              />
            </div>

            <div className="nfc-mobile-record-facts">
              <span>创建 <b>{formatDateTime(task.created_at)}</b></span>
              <span>耗时 <b>{formatElapsed(task.started_at, task.finished_at, currentTime)}</b></span>
            </div>

            {(task.error || task.error_code) && (
              <div className="nfc-mobile-record-error">
                {task.error_code ? `[${task.error_code}] ` : ''}
                {task.error || task.error_code}
              </div>
            )}

            <div className="nfc-mobile-record-actions">
              <Button type="text" icon={<EyeOutlined />} onClick={() => setSelectedTaskId(task.id)}>
                查看详情
              </Button>
              <TaskDeleteButton
                task={task}
                type="text"
                onSuccess={() => handleDeleted(task.id)}
              />
            </div>
          </article>
        ))
      )}
    </div>
  );

  return (
    <div className="nfc-operations-page nfc-tasks-page">
      <PageHeader
        eyebrow="Operations"
        title="任务中心"
        description="实时观察 Worker 的扫描、索引与计划执行任务；活动任务会自动刷新。"
        actions={
          <ActionBar compact>
            <TaskHistoryCleanupModal
              onCleaned={() => {
                setPage(1);
                setSelectedTaskId(null);
              }}
            />
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>
              刷新
            </Button>
          </ActionBar>
        }
      />

      <WorkerStatusCard />

      {isError && (
        <Alert
          type="error"
          showIcon
          className="nfc-page-alert"
          message="任务列表加载失败"
          description={
            typeof error === 'object' && error && 'message' in error
              ? String(error.message)
              : '无法连接到任务服务，请检查 NAS 服务端状态'
          }
        />
      )}

      <DataPanel
        title="任务队列"
        description="按状态和任务类型筛选；正在运行的任务会保留实时进度与 ETA。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} tasks</span>}
        className="nfc-panel-flush"
      >
        <ActionBar className="nfc-filter-bar">
          <label className="nfc-filter-control">
            <span>状态</span>
            <Select
              value={statusFilter}
              onChange={handleStatusFilterChange}
              options={STATUS_OPTIONS}
              popupMatchSelectWidth={false}
            />
          </label>
          <label className="nfc-filter-control">
            <span>任务类型</span>
            <Select
              value={jobTypeFilter}
              onChange={handleJobTypeFilterChange}
              options={JOB_TYPE_OPTIONS}
              popupMatchSelectWidth={false}
            />
          </label>
        </ActionBar>

        <ResponsiveDataView
          desktop={
            <Table
              dataSource={items}
              columns={columns}
              rowKey="id"
              loading={isLoading}
              scroll={{ x: 1160 }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={isFiltered ? '无匹配任务 (No matching tasks)' : '暂无任务 (No tasks yet)'}
                  />
                ),
              }}
              pagination={{
                current: page,
                pageSize,
                total: data?.total || 0,
                showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100', '200'],
                showTotal: (total) => `共 ${total} 条记录`,
                onChange: (p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                },
              }}
            />
          }
          mobile={
            <>
              {mobileCards}
              <div className="nfc-mobile-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={data?.total || 0}
                  showSizeChanger
                  pageSizeOptions={['20', '50', '100', '200']}
                  onChange={(p, ps) => {
                    setPage(p);
                    setPageSize(ps);
                  }}
                />
              </div>
            </>
          }
        />
      </DataPanel>

      <TaskDetailDrawer
        taskId={selectedTaskId}
        open={selectedTaskId !== null}
        onClose={() => setSelectedTaskId(null)}
        onViewTask={(newId) => setSelectedTaskId(newId)}
      />
    </div>
  );
};
