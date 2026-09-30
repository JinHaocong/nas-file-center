import React from 'react';
import { Button, Empty, Table } from 'antd';
import {
  ArrowRightOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  FolderViewOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  ScanOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { dashboardApi, scansApi, tasksApi } from '../../api/domain';
import { PageHeader } from '../../components/ui/PageHeader';
import { MetricCard } from '../../components/ui/MetricCard';
import { DataPanel } from '../../components/ui/DataPanel';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { useResponsive } from '../../hooks/useResponsive';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';

export const DashboardPage: React.FC = () => {
  useTitle('系统概览');
  const navigate = useNavigate();
  const { isMobile } = useResponsive();

  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery({
    queryKey: ['dashboardSummary'],
    queryFn: () => dashboardApi.getSummary(),
    refetchInterval: 10000,
  });

  const { data: scansData, isLoading: scansLoading } = useQuery({
    queryKey: ['recentScans'],
    queryFn: () => scansApi.listScans(1, 5),
  });

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ['recentTasks'],
    queryFn: () => tasksApi.listJobs(1, 5),
    refetchInterval: 5000,
  });

  const scanColumns = [
    {
      title: '扫描名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: any) => (
        <button
          type="button"
          className="nfc-table-link"
          onClick={() => navigate(`/scans/${record.id}`)}
        >
          {text}
        </button>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 124,
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: '重复组',
      dataIndex: 'total_groups',
      key: 'total_groups',
      width: 88,
      render: (value: number) => <span className="nfc-mono">{value ?? 0}</span>,
    },
    {
      title: '可释放空间',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      width: 122,
      render: (bytes: number) => (
        <span className={bytes > 0 ? 'nfc-data-emphasis' : 'nfc-table-muted'}>
          {formatBytes(bytes || 0)}
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 168,
      render: (val: string) => <span className="nfc-table-meta">{formatDateTime(val)}</span>,
    },
  ];

  const taskColumns = [
    {
      title: '任务',
      dataIndex: 'kind',
      key: 'kind',
      render: (kind: string, record: any) => (
        <div className="nfc-dashboard-task-identity">
          <strong>{kind}</strong>
          <span className="nfc-mono">#{record.id}</span>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 124,
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: '进度',
      key: 'progress',
      width: 150,
      render: (_: unknown, record: any) => {
        if (record.progress_total > 0) {
          const pct = Math.round((record.progress_current / record.progress_total) * 100);
          return <span className="nfc-mono">{record.progress_current}/{record.progress_total} · {pct}%</span>;
        }
        return record.progress_current > 0
          ? <span className="nfc-mono">{record.progress_current} 项</span>
          : <span className="nfc-table-muted">等待进度</span>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 168,
      render: (val: string) => <span className="nfc-table-meta">{formatDateTime(val)}</span>,
    },
  ];

  const quickActions = [
    {
      title: '开始精确扫描',
      description: '发现完全重复文件并生成只读扫描快照。',
      icon: <ScanOutlined />,
      onClick: () => navigate('/scans'),
    },
    {
      title: '更新文件索引',
      description: '刷新大型目录的增量元数据索引。',
      icon: <FolderOpenOutlined />,
      onClick: () => navigate('/indexes'),
    },
    {
      title: '整理目录结构',
      description: '进入目录整理的配置、预览与计划流程。',
      icon: <FolderViewOutlined />,
      onClick: () => navigate('/organizer'),
    },
  ];

  const scanItems = scansData?.items || [];
  const taskItems = tasksData?.items || [];
  const activeJobs = summary?.queued_or_running_jobs || 0;

  return (
    <div className="nfc-dashboard nfc-dashboard-page nfc-operations-page nfc-page-layout-dashboard">
      <PageHeader
        title="系统概览"
        description="先查看当前运行状态和需要继续处理的工作，再进入索引、扫描或执行计划。"
        actions={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => refetchSummary()}
            loading={summaryLoading}
          >
            刷新状态
          </Button>
        }
      />

      <section className="nfc-dashboard-priority" aria-label="当前运行状态">
        <div className="nfc-dashboard-priority-main">
          <div className="nfc-dashboard-priority-label">
            <ThunderboltOutlined />
            <span>后台任务</span>
          </div>
          <strong>{activeJobs > 0 ? `${activeJobs} 个任务正在运行或等待` : '当前没有运行中的后台任务'}</strong>
          <span>{activeJobs > 0 ? '可前往任务中心查看进度、日志和失败信息。' : '可以安全开始新的索引、扫描或计划工作。'}</span>
        </div>
        <Button type={activeJobs > 0 ? 'primary' : 'default'} onClick={() => navigate('/tasks')}>
          查看任务中心
        </Button>
      </section>

      <section className="nfc-dashboard-snapshot" aria-label="扫描快照说明">
        <InfoCircleOutlined />
        <div>
          <strong>最近扫描快照</strong>
          <span>
            {summary?.latest_scan_id
              ? `${summary.latest_scan_name || `扫描 #${summary.latest_scan_id}`} · ${summary.duplicate_group_count || 0} 个重复组 · 预计可释放 ${formatBytes(summary.latest_reclaimable_bytes || 0)}`
              : '尚无已完成扫描。重复组和可释放空间将在扫描完成后显示。'}
          </span>
        </div>
        <Button type="link" onClick={() => navigate('/scans')}>进入扫描去重</Button>
      </section>

      <section className="nfc-metric-grid nfc-dashboard-metric-grid" aria-label="运行摘要">
        <MetricCard
          label="已索引文件"
          value={summary?.indexed_files || 0}
          meta={`${summary?.indexed_folders || 0} 个目录`}
          icon={<DatabaseOutlined />}
        />
        <MetricCard
          label="重复组"
          value={summary?.latest_scan_id ? summary?.duplicate_group_count || 0 : '—'}
          meta={summary?.latest_scan_finished_at ? formatDateTime(summary.latest_scan_finished_at) : '等待扫描快照'}
          icon={<ScanOutlined />}
          tone="attention"
        />
        <MetricCard
          label="预计可释放"
          value={summary?.latest_scan_id ? formatBytes(summary?.latest_reclaimable_bytes || 0) : '—'}
          meta="来自最近一次已完成扫描"
          icon={<DeleteOutlined />}
          tone={summary?.latest_reclaimable_bytes ? 'success' : 'default'}
        />
        <MetricCard
          label="执行计划"
          value={summary?.plan_count || 0}
          meta="当前计划总数"
          icon={<ScheduleOutlined />}
        />
      </section>

      <div className="nfc-dashboard-layout">
        <main className="nfc-dashboard-main-column">
          <DataPanel
            title="最近扫描"
            description="查看最近的扫描状态和结果快照。"
            action={
              <Button type="link" onClick={() => navigate('/scans')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
            className="nfc-panel-flush"
          >
            {isMobile ? (
              <div className="nfc-mobile-activity-list">
                {scanItems.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无扫描任务" />
                ) : (
                  scanItems.map((item: any) => (
                    <button
                      type="button"
                      key={item.id}
                      className="nfc-mobile-activity-card"
                      onClick={() => navigate(`/scans/${item.id}`)}
                    >
                      <div className="nfc-mobile-activity-topline">
                        <strong>{item.name}</strong>
                        <StatusBadge status={item.status} />
                      </div>
                      <div className="nfc-mobile-activity-grid">
                        <span>重复组 <b>{item.total_groups ?? 0}</b></span>
                        <span>可释放 <b>{formatBytes(item.reclaimable_bytes || 0)}</b></span>
                      </div>
                      <div className="nfc-mobile-activity-meta">
                        {item.created_at ? formatDateTime(item.created_at) : '—'}
                      </div>
                    </button>
                  ))
                )}
              </div>
            ) : (
              <Table
                dataSource={scanItems}
                columns={scanColumns}
                rowKey="id"
                pagination={false}
                loading={scansLoading}
                size="small"
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无扫描任务" /> }}
              />
            )}
          </DataPanel>

          <DataPanel
            title="后台执行队列"
            description="正在运行或最近进入队列的 Worker 任务。"
            action={
              <Button type="link" onClick={() => navigate('/tasks')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
            className="nfc-panel-flush"
          >
            {isMobile ? (
              <div className="nfc-mobile-activity-list">
                {taskItems.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无后台任务" />
                ) : (
                  taskItems.map((item: any) => (
                    <div key={item.id} className="nfc-mobile-activity-card">
                      <div className="nfc-mobile-activity-topline">
                        <strong>{item.kind}</strong>
                        <StatusBadge status={item.status} />
                      </div>
                      <div className="nfc-mobile-activity-grid">
                        <span className="nfc-mono">#{item.id}</span>
                        <span>
                          进度{' '}
                          <b>
                            {item.progress_total > 0
                              ? `${item.progress_current}/${item.progress_total}`
                              : item.progress_current > 0
                                ? `${item.progress_current} 项`
                                : '—'}
                          </b>
                        </span>
                      </div>
                      <div className="nfc-mobile-activity-meta">
                        {item.created_at ? formatDateTime(item.created_at) : '—'}
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : (
              <Table
                dataSource={taskItems}
                columns={taskColumns}
                rowKey="id"
                pagination={false}
                loading={tasksLoading}
                size="small"
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无后台任务" /> }}
              />
            )}
          </DataPanel>
        </main>

        <aside className="nfc-dashboard-rail">
          <section className="nfc-dashboard-quick-section" aria-labelledby="nfc-dashboard-quick-title">
            <div className="nfc-dashboard-section-heading">
              <h2 id="nfc-dashboard-quick-title">常用入口</h2>
              <span>进入下一步工作</span>
            </div>
            <div className="nfc-quick-actions">
              {quickActions.map((action) => (
                <button
                  type="button"
                  key={action.title}
                  className="nfc-quick-action"
                  onClick={action.onClick}
                >
                  <span className="nfc-quick-action-icon" aria-hidden="true">{action.icon}</span>
                  <span className="nfc-quick-action-copy">
                    <strong>{action.title}</strong>
                    <span>{action.description}</span>
                  </span>
                  <ArrowRightOutlined className="nfc-quick-action-arrow" />
                </button>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
};
