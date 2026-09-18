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
      width: 132,
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: '重复组',
      dataIndex: 'total_groups',
      key: 'total_groups',
      width: 86,
    },
    {
      title: '可释放空间',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      width: 112,
      render: (bytes: number) => (
        <span className={bytes > 0 ? 'nfc-data-emphasis' : undefined}>{formatBytes(bytes)}</span>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 168,
      render: (val: string) => formatDateTime(val),
    },
  ];

  const taskColumns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 68,
      render: (id: number) => <span className="nfc-mono">#{id}</span>,
    },
    {
      title: '任务类型',
      dataIndex: 'kind',
      key: 'kind',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 132,
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: '进度',
      key: 'progress',
      width: 150,
      render: (_: any, record: any) => {
        if (record.progress_total > 0) {
          const pct = Math.round((record.progress_current / record.progress_total) * 100);
          return `${record.progress_current}/${record.progress_total} · ${pct}%`;
        }
        return record.progress_current > 0 ? `${record.progress_current} 项` : '—';
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 168,
      render: (val: string) => formatDateTime(val),
    },
  ];

  const quickActions = [
    {
      title: '开始精确扫描',
      description: '使用 fclones 发现完全重复文件。',
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
      description: '进入 Organizer 预览和规划目录整理。',
      icon: <FolderViewOutlined />,
      onClick: () => navigate('/organizer'),
    },
  ];

  const scanItems = scansData?.items || [];
  const taskItems = tasksData?.items || [];

  return (
    <div className="nfc-dashboard nfc-dashboard-page nfc-operations-page">
      <PageHeader
        eyebrow="Operations overview"
        title="系统概览"
        description="NAS 文件中心的索引、扫描、执行计划与后台任务状态。"
        actions={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => refetchSummary()}
            loading={summaryLoading}
            className="nfc-secondary-action"
          >
            刷新
          </Button>
        }
      />

      <div className="nfc-snapshot-note" role="note">
        <InfoCircleOutlined />
        <div>
          <strong>扫描快照</strong>
          <span>
            重复组和可释放空间来自最近一次已完成扫描；需要最新结果时请重新发起扫描。
          </span>
        </div>
      </div>

      <section className="nfc-metric-grid" aria-label="核心运行指标">
        <MetricCard
          label="已索引文件"
          value={summary?.indexed_files || 0}
          meta={`${summary?.indexed_folders || 0} 个目录`}
          icon={<DatabaseOutlined />}
        />
        <MetricCard
          label="最近一次扫描发现"
          value={summary?.latest_scan_id ? summary?.duplicate_group_count || 0 : '—'}
          meta={
            summary?.latest_scan_id
              ? summary.latest_scan_name || `扫描 #${summary.latest_scan_id}`
              : '暂无已完成扫描'
          }
          icon={<ScanOutlined />}
          tone="attention"
        />
        <MetricCard
          label="最近一次扫描预计可释放"
          value={summary?.latest_scan_id ? formatBytes(summary?.latest_reclaimable_bytes || 0) : '—'}
          meta={
            summary?.latest_scan_finished_at
              ? formatDateTime(summary.latest_scan_finished_at)
              : '等待扫描快照'
          }
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
            description="最近的重复文件扫描及其快照结果。"
            action={
              <Button type="link" onClick={() => navigate('/scans')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
          >
            {isMobile ? (
              <div className="nfc-mobile-activity-list">
                {scanItems.length === 0 ? (
                  <Empty description="暂无扫描任务" />
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
                locale={{ emptyText: <Empty description="暂无扫描任务" /> }}
              />
            )}
          </DataPanel>

          <DataPanel
            title="后台执行队列"
            description="Worker 正在处理或等待处理的任务。"
            action={
              <Button type="link" onClick={() => navigate('/tasks')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
          >
            {isMobile ? (
              <div className="nfc-mobile-activity-list">
                {taskItems.length === 0 ? (
                  <Empty description="暂无执行中任务" />
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
                locale={{ emptyText: <Empty description="暂无执行中任务" /> }}
              />
            )}
          </DataPanel>
        </main>

        <aside className="nfc-dashboard-rail">
          <DataPanel
            title="快速操作"
            description="进入最常用的 NAS 工作流。"
          >
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
          </DataPanel>

          <DataPanel
            title="运行摘要"
            description="用于快速判断当前系统是否需要关注。"
          >
            <div className="nfc-summary-list">
              <div className="nfc-summary-row">
                <span><ThunderboltOutlined /> 活跃任务</span>
                <strong>{summary?.queued_or_running_jobs || 0}</strong>
              </div>
              <div className="nfc-summary-row">
                <span><ScanOutlined /> 扫描总数</span>
                <strong>{summary?.scan_count || 0}</strong>
              </div>
              <div className="nfc-summary-row">
                <span><ScheduleOutlined /> 执行计划</span>
                <strong>{summary?.plan_count || 0}</strong>
              </div>
            </div>
          </DataPanel>
        </aside>
      </div>
    </div>
  );
};
