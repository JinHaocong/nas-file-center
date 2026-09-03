import React, { useState } from 'react';
import { Card, Table, Typography, Tag, Progress, Button, Space, Modal, Alert } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';
import { WorkJob } from '../../types';

const { Title, Text } = Typography;

export const TasksPage: React.FC = () => {
  useTitle('任务中心');
  const [selectedJob, setSelectedJob] = useState<WorkJob | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['workJobsList', page, pageSize],
    queryFn: () => tasksApi.listJobs(page, pageSize),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some((j) => j.status === 'queued' || j.status === 'running');
      return hasActive ? 3000 : false;
    },
  });

  const columns = [
    {
      title: '任务 ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
      render: (id: number) => <Text strong>#{id}</Text>,
    },
    {
      title: '任务类型',
      dataIndex: 'kind',
      key: 'kind',
      render: (kind: string) => <Tag color="blue">{kind}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const item = STATUS_MAP[status] || { label: status, color: 'default' };
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: '进度',
      key: 'progress',
      width: 200,
      render: (_: any, record: WorkJob) => {
        if (record.progress_total > 0) {
          const percent = Math.min(
            100,
            Math.round((record.progress_current / record.progress_total) * 100)
          );
          return (
            <div>
              <Progress
                percent={percent}
                size="small"
                status={record.status === 'failed' ? 'exception' : undefined}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {record.progress_current} / {record.progress_total}
              </Text>
            </div>
          );
        }
        if (record.progress_current > 0) {
          return <Text>{record.progress_current} 项</Text>;
        }
        return '-';
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '耗时 / 完成时间',
      key: 'duration',
      render: (_: any, record: WorkJob) => {
        if (record.finished_at) {
          return formatDateTime(record.finished_at);
        }
        if (record.started_at) {
          return <Tag color="processing">正在执行...</Tag>;
        }
        return <Text type="secondary">排队等待中</Text>;
      },
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: WorkJob) => (
        <Button size="small" type="link" onClick={() => setSelectedJob(record)}>
          任务状态详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            后台任务中心
          </Title>
          <Text type="secondary">实时监控后台 Worker 扫描、索引与计划执行状态</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
          刷新
        </Button>
      </div>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={data?.items || []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          pagination={{
            current: page,
            pageSize,
            total: data?.total || 0,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      </Card>

      <Modal
        title={`任务详情 #${selectedJob?.id} (${selectedJob?.kind})`}
        open={!!selectedJob}
        onCancel={() => setSelectedJob(null)}
        footer={[
          <Button key="close" onClick={() => setSelectedJob(null)}>
            关闭
          </Button>,
        ]}
        width={600}
      >
        {selectedJob && (
          <Space direction="vertical" style={{ width: '100%', marginTop: 12 }} size="middle">
            {selectedJob.error && (
              <Alert
                message="任务失败原因"
                description={selectedJob.error}
                type="error"
                showIcon
              />
            )}
            <div>
              <Text strong>状态：</Text>
              <Tag color={STATUS_MAP[selectedJob.status]?.color}>
                {STATUS_MAP[selectedJob.status]?.label || selectedJob.status}
              </Tag>
            </div>
            <div>
              <Text strong>创建时间：</Text>
              <Text>{formatDateTime(selectedJob.created_at)}</Text>
            </div>
            <div>
              <Text strong>开始时间：</Text>
              <Text>{formatDateTime(selectedJob.started_at)}</Text>
            </div>
            <div>
              <Text strong>结束时间：</Text>
              <Text>{formatDateTime(selectedJob.finished_at)}</Text>
            </div>
            <div>
              <Text strong>内部状态数据 (State JSON)：</Text>
              <pre
                style={{
                  background: 'rgba(0,0,0,0.04)',
                  padding: 12,
                  borderRadius: 8,
                  marginTop: 6,
                  maxHeight: 200,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(selectedJob.state, null, 2)}
              </pre>
            </div>
          </Space>
        )}
      </Modal>
    </div>
  );
};
