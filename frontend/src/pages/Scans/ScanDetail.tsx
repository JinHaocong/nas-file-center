import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Alert,
  Spin,
  Tooltip,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { scansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';
import { DedupePlanModal } from './DedupePlanModal';
import { DuplicateGroup } from '../../types';
import { ScanDeleteButton } from '../../components/scans/ScanDeleteButton';

const { Title, Text } = Typography;

export const ScanDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const scanId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useTitle(`扫描详情 #${scanId}`);

  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const deleteScanMutation = useMutation({
    mutationFn: () => scansApi.deleteScan(scanId),
    onSuccess: () => {
      message.success(`扫描 #${scanId} 已成功删除`);
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      navigate('/scans');
    },
    onError: (err: any) => {
      message.error(err.message || '删除扫描失败');
    },
  });


  const { data: scan, isLoading: scanLoading, refetch: refetchScan } = useQuery({
    queryKey: ['scanDetail', scanId],
    queryFn: () => scansApi.getScanDetail(scanId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 3000 : false;
    },
  });

  const { data: groupsData, isLoading: groupsLoading, refetch: refetchGroups } = useQuery({
    queryKey: ['scanGroups', scanId, page, pageSize],
    queryFn: () => scansApi.getScanGroups(scanId, page, pageSize),
    enabled: scan?.status === 'completed',
  });

  if (scanLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!scan) {
    return (
      <Alert
        message="扫描任务不存在"
        description={`未找到 ID 为 #${scanId} 的扫描任务`}
        type="error"
        showIcon
        action={<Button onClick={() => navigate('/scans')}>返回扫描列表</Button>}
      />
    );
  }

  const statusConfig = STATUS_MAP[scan.status] || { label: scan.status, color: 'default' };

  const groupColumns = [
    {
      title: '组 ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: '内容哈希 (Hash)',
      dataIndex: 'content_hash',
      key: 'content_hash',
      render: (hash: string) => (
        <Tooltip title={hash}>
          <Text code copyable={{ text: hash }}>
            {hash.substring(0, 16)}...
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '单文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      render: (bytes: number) => formatBytes(bytes),
    },
    {
      title: '重复副本数',
      dataIndex: 'member_count',
      key: 'member_count',
      render: (count: number) => <Tag color="blue">{count} 份</Tag>,
    },
    {
      title: '预计可释放',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      render: (bytes: number) => (
        <Text type="success" strong>
          {formatBytes(bytes)}
        </Text>
      ),
    },
  ];

  const expandedRowRender = (record: DuplicateGroup) => {
    const memberColumns = [
      {
        title: '根目录 ID',
        dataIndex: 'root_id',
        key: 'root_id',
        width: 100,
        render: (rId: number) => <Tag>Root #{rId}</Tag>,
      },
      {
        title: '相对路径',
        dataIndex: 'relative_path',
        key: 'relative_path',
        render: (p: string) => <Text copyable>{p}</Text>,
      },
      {
        title: '完整绝对路径',
        dataIndex: 'path',
        key: 'path',
        render: (p: string) => <Text code copyable>{p}</Text>,
      },
      {
        title: '大小',
        dataIndex: 'size',
        key: 'size',
        width: 120,
        render: (bytes: number) => formatBytes(bytes),
      },
    ];

    return (
      <Table
        columns={memberColumns}
        dataSource={record.members}
        pagination={false}
        rowKey="id"
        size="small"
      />
    );
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/scans')}>
            返回列表
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            扫描详情: {scan.name}
          </Title>
          <Tag color={statusConfig.color} style={{ fontSize: 13, padding: '2px 8px' }}>
            {statusConfig.label}
          </Tag>
          {scan.has_dependent_plan && (
            <Tag color="gold" style={{ fontSize: 13, padding: '2px 8px' }}>
              已生成关联计划
            </Tag>
          )}
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => { refetchScan(); refetchGroups(); }}>
            刷新
          </Button>
          <ScanDeleteButton
            scan={scan}
            onDelete={() => deleteScanMutation.mutate()}
            loading={deleteScanMutation.isPending}
            buttonText="删除扫描"
            type="default"
          />
          {scan.status === 'completed' && scan.total_groups > 0 && (
            <Button type="primary" icon={<ScheduleOutlined />} onClick={() => setPlanModalOpen(true)}>
              生成去重计划
            </Button>
          )}
        </Space>
      </div>

      {scan.error && (
        <Alert
          message="扫描执行失败"
          description={scan.error}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Descriptions bordered column={{ xs: 1, sm: 2, md: 3 }}>
          <Descriptions.Item label="任务 ID">#{scan.id}</Descriptions.Item>
          <Descriptions.Item label="扫描模式">
            <Tag color={scan.mode === 'isolate' ? 'purple' : 'blue'}>
              {scan.mode === 'isolate' ? 'A/B 跨目录隔离' : '标准扫描'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatDateTime(scan.created_at)}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{scan.started_at ? formatDateTime(scan.started_at) : '-'}</Descriptions.Item>
          <Descriptions.Item label="完成时间">{scan.finished_at ? formatDateTime(scan.finished_at) : '-'}</Descriptions.Item>
          <Descriptions.Item label="发现重复组数">
            <Text strong style={{ fontSize: 16, color: '#fa8c16' }}>
              {scan.total_groups.toLocaleString()} 组
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="重复文件总数">
            <Text strong style={{ fontSize: 16 }}>
              {scan.total_files_in_groups.toLocaleString()} 个
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="预计可释放容量">
            <Text strong style={{ fontSize: 16, color: '#52c41a' }}>
              {formatBytes(scan.reclaimable_bytes)}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="扫描根目录" span={3}>
            <Space wrap>
              {scan.roots.map((root, idx) => (
                <Tag key={idx} icon={<CheckCircleOutlined />} color="cyan">
                  {root}
                </Tag>
              ))}
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {scan.status === 'completed' && (
        <Card title={`重复文件组列表 (${groupsData?.total || 0} 组)`} bordered={false} style={{ borderRadius: 12 }}>
          <Table
            dataSource={groupsData?.items || []}
            columns={groupColumns}
            rowKey="id"
            loading={groupsLoading}
            expandable={{ expandedRowRender }}
            pagination={{
              current: page,
              pageSize,
              total: groupsData?.total || 0,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50', '100'],
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        </Card>
      )}

      <DedupePlanModal scanId={scanId} open={planModalOpen} onClose={() => setPlanModalOpen(false)} />
    </div>
  );
};
