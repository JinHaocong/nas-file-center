import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/domain';
import { ConsoleIcon } from './ui/ConsoleIcon';

export const WorkerStatusBadge: React.FC = () => {
  const { data: summary, isError } = useQuery({
    queryKey: ['dashboardSummary'],
    queryFn: () => dashboardApi.getSummary(),
    refetchInterval: 5000,
  });
  if (!summary) {
    return <span className="nfc-header-status-badge is-loading" role="status"
      title={isError ? '无法获取队列状态' : '正在读取任务队列'}>
      <ConsoleIcon name="activity" size={14} /> 队列状态未知
    </span>;
  }
  const activeJobs = summary.queued_or_running_jobs || 0;
  if (activeJobs > 0) {
    return <span className="nfc-header-status-badge is-processing" role="status"
      title={'当前任务队列有 ' + activeJobs + ' 个正在运行或等待中的任务'}>
      <ConsoleIcon name="activity" size={14} /> 队列 {activeJobs}
    </span>;
  }
  return <span className="nfc-header-status-badge is-idle" role="status"
    title="当前任务队列没有排队或正在执行的任务">
    <ConsoleIcon name="check-circle" size={14} /> 队列空闲
  </span>;
};
