import React, { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Typography,
  Tag,
  Button,
  Space,
  Select,
  Alert,
  Tooltip,
  Empty,
} from 'antd';
import { ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { tasksApi } from '../../api/tasks';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime, formatElapsed } from '../../utils/format';
import { TaskItem, TaskStatus } from '../../types/task';
import { WorkerStatusCard } from '../../components/tasks/WorkerStatusCard';
import { TaskStatusTag } from '../../components/tasks/TaskStatusTag';
import { TaskProgress } from '../../components/tasks/TaskProgress';
import { TaskDetailDrawer } from '../../components/tasks/TaskDetailDrawer';

const { Title, Text } = Typography;

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

  // Local elapsed ticker: ticks once per second ONLY if any task is currently running
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

  const isFiltered = statusFilter !== 'all' || jobTypeFilter !== 'all';

  const columns = [
    {
      title: '任务 ID',
      dataIndex: 'id',
      key: 'id',
      width: 90,
      render: (id: number) => (
        <Button
          type="link"
          style={{ padding: 0, fontWeight: 600 }}
          onClick={() => setSelectedTaskId(id)}
        >
          #{id}
        </Button>
      ),
    },
    {
      title: '任务类型',
      dataIndex: 'job_type',
      key: 'job_type',
      width: 130,
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: TaskStatus) => <TaskStatusTag status={status} />,
    },
    {
      title: '进度',
      key: 'progress',
      width: 220,
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
      width: 160,
      render: (val: string | null) => (
        <Text style={{ fontSize: 12 }}>{formatDateTime(val)}</Text>
      ),
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 160,
      render: (val: string | null) => (
        <Text style={{ fontSize: 12 }}>{formatDateTime(val)}</Text>
      ),
    },
    {
      title: '完成时间',
      dataIndex: 'finished_at',
      key: 'finished_at',
      width: 160,
      render: (val: string | null) => (
        <Text style={{ fontSize: 12 }}>{formatDateTime(val)}</Text>
      ),
    },
    {
      title: '执行耗时',
      key: 'elapsed',
      width: 110,
      render: (_: unknown, record: TaskItem) => {
        const elapsedStr = formatElapsed(record.started_at, record.finished_at, currentTime);
        return <Text style={{ fontSize: 12 }}>{elapsedStr}</Text>;
      },
    },
    {
      title: '错误信息',
      key: 'error',
      width: 180,
      render: (_: unknown, record: TaskItem) => {
        if (!record.error && !record.error_code) {
          return <Text type="secondary">-</Text>;
        }
        const fullErr = record.error || record.error_code || '';
        const displayErr = fullErr.length > 25 ? `${fullErr.slice(0, 25)}...` : fullErr;
        return (
          <Tooltip title={fullErr}>
            <Text type="danger" style={{ fontSize: 12, cursor: 'pointer' }}>
              {record.error_code ? `[${record.error_code}] ` : ''}
              {displayErr}
            </Text>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right' as const,
      render: (_: unknown, record: TaskItem) => (
        <Button
          size="small"
          type="link"
          icon={<EyeOutlined />}
          onClick={() => setSelectedTaskId(record.id)}
        >
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0 }}>
            任务中心
          </Title>
          <Text type="secondary">
            实时监控后台 Worker 扫描、索引与计划任务状态
          </Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => refetch()}
          loading={isFetching}
        >
          刷新
        </Button>
      </div>

      {/* Top Worker Status Banner */}
      <WorkerStatusCard />

      {/* Error alert if task list fails */}
      {isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="任务列表加载失败"
          description={
            typeof error === 'object' && error && 'message' in error
              ? String(error.message)
              : '无法连接到任务服务，请检查 NAS 服务端状态'
          }
        />
      )}

      {/* Main Table Card with Filters */}
      <Card bordered={false} style={{ borderRadius: 12 }}>
        {/* Filters Toolbar */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <Space wrap size={12}>
            <Space size={6}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                状态筛选:
              </Text>
              <Select
                value={statusFilter}
                onChange={handleStatusFilterChange}
                style={{ width: 130 }}
                options={[
                  { label: '全部状态', value: 'all' },
                  { label: '排队中 (queued)', value: 'queued' },
                  { label: '执行中 (running)', value: 'running' },
                  { label: '已暂停 (paused)', value: 'paused' },
                  { label: '取消中 (cancel_requested)', value: 'cancel_requested' },
                  { label: '已取消 (cancelled)', value: 'cancelled' },
                  { label: '已失败 (failed)', value: 'failed' },
                  { label: '已完成 (completed)', value: 'completed' },
                ]}
              />
            </Space>

            <Space size={6}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                任务类型:
              </Text>
              <Select
                value={jobTypeFilter}
                onChange={handleJobTypeFilterChange}
                style={{ width: 140 }}
                options={[
                  { label: '全部类型', value: 'all' },
                  { label: 'fclones-scan', value: 'fclones-scan' },
                  { label: 'index-root', value: 'index-root' },
                ]}
              />
            </Space>
          </Space>

          {data?.total !== undefined && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 {data.total} 个任务
            </Text>
          )}
        </div>

        {/* Tasks Table with Server-Side Pagination */}
        <Table
          dataSource={data?.items || []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          scroll={{ x: 1200 }}
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
      </Card>

      {/* Task Detail Drawer */}
      <TaskDetailDrawer
        taskId={selectedTaskId}
        open={selectedTaskId !== null}
        onClose={() => setSelectedTaskId(null)}
        onViewTask={(newId) => setSelectedTaskId(newId)}
      />
    </div>
  );
};
