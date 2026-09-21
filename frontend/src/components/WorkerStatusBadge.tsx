import React from 'react';
import { Tag, Tooltip } from 'antd';
import { SyncOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/domain';

export const WorkerStatusBadge: React.FC = () => {
  const { data: summary } = useQuery({
    queryKey: ['dashboardSummary'],
    queryFn: () => dashboardApi.getSummary(),
    refetchInterval: 5000,
  });

  const activeJobs = summary?.queued_or_running_jobs || 0;

  if (activeJobs > 0) {
    return (
      <Tooltip title={`当前任务队列有 ${activeJobs} 个进行中或等待中的任务`}>
        <Tag color="processing" icon={<SyncOutlined spin />} className="nfc-header-status-badge is-processing">
          队列 {activeJobs}
        </Tag>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="当前任务队列空闲">
      <Tag color="default" icon={<CheckCircleOutlined />} className="nfc-header-status-badge is-idle">
        队列空闲
      </Tag>
    </Tooltip>
  );
};
