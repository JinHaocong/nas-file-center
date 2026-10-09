import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { dashboardApi, scansApi, tasksApi } from '../../api/domain';
import { PageHeader } from '../../components/ui/PageHeader';
import { MetricCard } from '../../components/ui/MetricCard';
import { DataPanel } from '../../components/ui/DataPanel';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import type { ConsoleIconName } from '../../components/ui/ConsoleIcon';
import { useResponsive } from '../../hooks/useResponsive';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';

interface QuickAction {
  title: string;
  description: string;
  path: string;
  icon: ConsoleIconName;
  tone: string;
}

const quickActions: QuickAction[] = [
  { title: '精确去重', description: '扫描并核验重复文件', path: '/scans', icon: 'layers', tone: 'blue' },
  { title: '批量重命名', description: '安全预览文件名变更', path: '/rename', icon: 'pencil', tone: 'violet' },
  { title: '双目录差异', description: '比较两处目录的变化', path: '/directory-diff', icon: 'git-compare', tone: 'mint' },
  { title: '文件名巡检', description: '识别异常文件名', path: '/filename-audit', icon: 'file-search', tone: 'amber' },
];

const taskStateLabel: Record<string, string> = {
  queued: '等待中',
  running: '运行中',
  paused: '已暂停',
  cancel_requested: '取消中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export const DashboardPage: React.FC = () => {
  useTitle('系统概览');
  const navigate = useNavigate();
  const { isMobile } = useResponsive();
  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary, isError: summaryError } = useQuery({
    queryKey: ['dashboardSummary'],
    queryFn: () => dashboardApi.getSummary(),
    refetchInterval: 10000,
  });
  const { data: scansData, isLoading: scansLoading, isError: scansError } = useQuery({
    queryKey: ['recentScans'],
    queryFn: () => scansApi.listScans(1, 5),
  });
  const { data: tasksData, isLoading: tasksLoading, isError: tasksError } = useQuery({
    queryKey: ['recentTasks'],
    queryFn: () => tasksApi.listJobs(1, 5),
    refetchInterval: 5000,
  });

  const scanItems = scansData?.items || [];
  const taskItems = tasksData?.items || [];
  const activeTaskCount = summary?.queued_or_running_jobs || 0;
  const completedInRecent = taskItems.filter(task => task.status === 'completed').length;
  const runningInRecent = taskItems.filter(task => ['running', 'queued'].includes(task.status)).length;
  const failedInRecent = taskItems.filter(task => task.status === 'failed').length;

  return (
    <div className="nfc-dashboard nfc-dashboard-page nfc-operations-page nfc-page-layout-dashboard nfc-v2-dashboard">
      <section className="nfc-v2-dashboard-hero" aria-label="NAS File Center 工作台">
        <div className="nfc-v2-hero-copy">
          <div className="nfc-v2-hero-eyebrow">
            <span className="nfc-v2-hero-dot" /> FILE OPERATIONS CONTROL CENTER
          </div>
          <PageHeader
            title="NAS File Center"
            description="安全、透明地管理大规模 NAS 文件。先预览、再确认，每一步都可追溯。"
            actions={
              <button type="button" className="nfc-v2-secondary-button"
                onClick={() => refetchSummary()} disabled={summaryLoading}>
                <ConsoleIcon name="refresh" size={16} /> 刷新数据
              </button>
            }
          />
          <div className="nfc-v2-hero-caption">
            <ConsoleIcon name="shield-check" size={16} />
            所有文件变更均通过执行计划校验与安全执行
          </div>
        </div>
        <div className="nfc-v2-hero-illustration" aria-hidden="true">
          <div className="nfc-v2-device">
            {[0, 1, 2, 3].map(index => (
              <div className="nfc-v2-device-bay" key={index}>
                <span /><i /><i />
              </div>
            ))}
          </div>
          <div className="nfc-v2-device-shadow" />
        </div>
      </section>

      {summaryError && <div className="nfc-v2-error-note" role="alert">
        系统摘要暂时无法获取，请检查 API 连接或稍后刷新。
      </div>}

      <section className="nfc-v2-dashboard-metrics" aria-label="核心运行指标">
        <div className="nfc-metric-grid">
          <MetricCard label="已索引文件"
            value={(summary?.indexed_files || 0).toLocaleString()}
            meta={summaryLoading ? '读取中…' : (summary?.indexed_folders || 0).toLocaleString() + ' 个目录'}
            icon={<ConsoleIcon name="database" size={20} />} />
          <MetricCard label="最近一次扫描发现"
            value={summary?.latest_scan_id ? (summary.duplicate_group_count || 0).toLocaleString() : '—'}
            meta={summary?.latest_scan_name || '暂无已完成扫描'}
            icon={<ConsoleIcon name="layers" size={20} />} tone="attention" />
          <MetricCard label="最近一次扫描预计可释放"
            value={summary?.latest_scan_id ? formatBytes(summary.latest_reclaimable_bytes || 0) : '—'}
            meta={summary?.latest_scan_finished_at
              ? formatDateTime(summary.latest_scan_finished_at) : '等待扫描快照'}
            icon={<ConsoleIcon name="archive" size={20} />} tone="success" />
          <MetricCard label="执行计划"
            value={(summary?.plan_count || 0).toLocaleString()}
            meta="现有计划总数"
            icon={<ConsoleIcon name="list-checks" size={20} />} />
        </div>
      </section>

      <div className="nfc-v2-dashboard-content">
        <div className="nfc-dashboard-main-column">
          <DataPanel title="最近扫描" description="最近的精确去重扫描及其文件快照"
            action={<button type="button" className="nfc-v2-text-link" onClick={() => navigate('/scans')}>
              查看全部 <ConsoleIcon name="arrow-right" size={15} />
            </button>}>
            {scansError ? <div className="nfc-v2-list-state">扫描列表加载失败，请稍后重试。</div>
              : scansLoading ? <div className="nfc-v2-list-state">正在获取最近扫描…</div>
              : scanItems.length === 0 ? <div className="nfc-v2-list-state">还没有扫描记录。可以从快捷入口开始第一次扫描。</div>
              : isMobile ? (
                <div className="nfc-mobile-activity-list">
                  {scanItems.map(item => (
                    <button type="button" key={item.id} className="nfc-mobile-activity-card"
                      onClick={() => navigate('/scans/' + item.id)}>
                      <div className="nfc-mobile-activity-topline"><strong>{item.name}</strong><StatusBadge status={item.status} /></div>
                      <div className="nfc-mobile-activity-grid">
                        <span>重复组 <b>{item.total_groups ?? 0}</b></span>
                        <span>可释放 <b>{formatBytes(item.reclaimable_bytes || 0)}</b></span>
                      </div>
                      <span className="nfc-mobile-activity-meta">{formatDateTime(item.created_at)}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="nfc-v2-table-scroll">
                  <table className="nfc-v2-data-table">
                    <thead><tr><th>扫描名称</th><th>状态</th><th>重复组</th><th>可释放空间</th><th>创建时间</th><th aria-label="操作" /></tr></thead>
                    <tbody>
                      {scanItems.map(item => (
                        <tr key={item.id}>
                          <td><button className="nfc-v2-row-link" type="button"
                            onClick={() => navigate('/scans/' + item.id)}>
                            <ConsoleIcon name="file-search" size={17} />{item.name}
                          </button></td>
                          <td><StatusBadge status={item.status} /></td>
                          <td className="nfc-v2-numeric">{item.total_groups.toLocaleString()}</td>
                          <td className="nfc-v2-numeric">{formatBytes(item.reclaimable_bytes)}</td>
                          <td className="nfc-v2-date">{formatDateTime(item.created_at)}</td>
                          <td><button type="button" className="nfc-v2-row-action"
                            onClick={() => navigate('/scans/' + item.id)} aria-label={'查看扫描 ' + item.name}>
                            <ConsoleIcon name="chevron-right" size={17} /></button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </DataPanel>

          <DataPanel title="后台任务" description="Worker 执行队列与最近任务状态"
            action={<button type="button" className="nfc-v2-text-link" onClick={() => navigate('/tasks')}>
              任务中心 <ConsoleIcon name="arrow-right" size={15} />
            </button>}>
            {tasksError ? <div className="nfc-v2-list-state">任务列表加载失败，请稍后重试。</div>
              : tasksLoading ? <div className="nfc-v2-list-state">正在获取任务…</div>
              : taskItems.length === 0 ? <div className="nfc-v2-list-state">暂无后台任务。</div>
              : isMobile ? (
                <div className="nfc-mobile-activity-list">
                  {taskItems.map(item => (
                    <div key={item.id} className="nfc-mobile-activity-card">
                      <div className="nfc-mobile-activity-topline"><strong>任务 #{item.id} · {item.kind}</strong><StatusBadge status={item.status} /></div>
                      <div className="nfc-mobile-activity-grid">
                        <span>进度 <b>{item.progress_total > 0 ? item.progress_current + '/' + item.progress_total : '—'}</b></span>
                        <span>{taskStateLabel[item.status] || item.status}</span>
                      </div>
                      <span className="nfc-mobile-activity-meta">{formatDateTime(item.created_at)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="nfc-v2-table-scroll">
                  <table className="nfc-v2-data-table">
                    <thead><tr><th>任务</th><th>状态</th><th>进度</th><th>创建时间</th></tr></thead>
                    <tbody>
                      {taskItems.map(item => (
                        <tr key={item.id}>
                          <td><span className="nfc-v2-task-icon"><ConsoleIcon name="activity" size={17} /></span>
                            <strong>#{item.id}</strong><span className="nfc-v2-task-kind">{item.kind}</span></td>
                          <td><StatusBadge status={item.status} /></td>
                          <td className="nfc-v2-numeric">
                            {item.progress_total > 0 ? item.progress_current + ' / ' + item.progress_total : '—'}
                          </td>
                          <td className="nfc-v2-date">{formatDateTime(item.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </DataPanel>
        </div>

        <aside className="nfc-dashboard-rail">
          <DataPanel title="快捷入口" description="常用 NAS 文件工作流">
            <div className="nfc-v2-quick-grid">
              {quickActions.map(action => (
                <button className="nfc-quick-action" type="button" key={action.path}
                  onClick={() => navigate(action.path)}>
                  <span className={'nfc-quick-action-icon nfc-v2-tone-' + action.tone}>
                    <ConsoleIcon name={action.icon} size={19} />
                  </span>
                  <span className="nfc-quick-action-copy">
                    <strong>{action.title}</strong><span>{action.description}</span>
                  </span>
                  <ConsoleIcon className="nfc-quick-action-arrow" name="chevron-right" size={16} />
                </button>
              ))}
            </div>
          </DataPanel>

          <DataPanel title="运行快照" description="来自 API 的最新统计，非历史趋势预测">
            <div className="nfc-v2-runtime-summary">
              <div className="nfc-v2-runtime-header">
                <span className="nfc-v2-runtime-mark"><ConsoleIcon name="activity" size={18} /></span>
                <span>当前活跃队列</span>
                <strong>{activeTaskCount}</strong>
              </div>
              <div className="nfc-v2-runtime-meters">
                <div><span>最近 {taskItems.length} 项任务 · 已完成</span><strong>{completedInRecent}</strong></div>
                <div className="nfc-v2-meter"><span style={{ width: taskItems.length ? (completedInRecent / taskItems.length * 100) + '%' : '0%' }} /></div>
                <div><span>正在运行或等待</span><strong>{runningInRecent}</strong></div>
                <div className="nfc-v2-meter is-blue"><span style={{ width: taskItems.length ? (runningInRecent / taskItems.length * 100) + '%' : '0%' }} /></div>
                <div><span>执行失败</span><strong>{failedInRecent}</strong></div>
                <div className="nfc-v2-meter is-red"><span style={{ width: taskItems.length ? (failedInRecent / taskItems.length * 100) + '%' : '0%' }} /></div>
              </div>
              <div className="nfc-v2-runtime-note">
                <ConsoleIcon name="shield-check" size={17} />
                <span>执行前请先核对 Preview、冻结和实时校验结果。安全模式不会被界面绕过。</span>
              </div>
            </div>
          </DataPanel>
        </aside>
      </div>

      <div className="nfc-snapshot-note nfc-v2-snapshot-note" role="note">
        <ConsoleIcon name="file-text" size={17} />
        <span><strong>扫描快照</strong>重复组和可释放空间来自最近一次已完成扫描；需要最新结果时请重新发起扫描。</span>
      </div>
    </div>
  );
};
