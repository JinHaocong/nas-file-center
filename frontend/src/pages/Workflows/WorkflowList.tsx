import React, { useState } from 'react';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
  Switch,
  Popconfirm,
  message,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  HistoryOutlined,
  EditOutlined,
  DeleteOutlined,
  FileTextOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import { WorkflowListItem } from '../../types/workflow';
import { RevisionDrawer } from '../../components/workflows/RevisionDrawer';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';

const { Title, Text } = Typography;

export const WorkflowListPage: React.FC = () => {
  useTitle('工作流中心');
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedWorkflowForRevision, setSelectedWorkflowForRevision] = useState<WorkflowListItem | null>(null);

  const {
    data: workflows,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['workflowsList', includeArchived],
    queryFn: () => workflowApi.listWorkflows(includeArchived),
  });

  const archiveMutation = useMutation({
    mutationFn: (wf: WorkflowListItem) =>
      workflowApi.archiveWorkflow(wf.id, wf.current_revision),
    onSuccess: () => {
      message.success('工作流已成功归档');
      refetch();
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '归档失败');
    },
  });

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
      render: (id: number) => <Text strong>#{id}</Text>,
    },
    {
      title: '工作流名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: WorkflowListItem) => (
        <Space direction="vertical" size={2}>
          <Text strong>
            {name}
          </Text>
          {record.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '执行模式',
      dataIndex: 'mode',
      key: 'mode',
      width: 140,
      render: (mode: 'file' | 'organizer') =>
        mode === 'file' ? (
          <Tag color="blue" icon={<FileTextOutlined />}>
            文件规则流
          </Tag>
        ) : (
          <Tag color="purple" icon={<AppstoreOutlined />}>
            目录整理流
          </Tag>
        ),
    },
    {
      title: '当前版本',
      dataIndex: 'current_revision',
      key: 'current_revision',
      width: 90,
      render: (rev: number) => <Tag color="geekblue">r{rev}</Tag>,
    },
    {
      title: '类别',
      dataIndex: 'is_builtin',
      key: 'is_builtin',
      width: 90,
      render: (builtin: boolean) =>
        builtin ? <Tag color="gold">内置预置</Tag> : <Tag color="default">用户自建</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'archived_at',
      key: 'archived_at',
      width: 100,
      render: (archived: string | null) =>
        archived ? <Tag color="error">已归档</Tag> : <Tag color="success">启用中</Tag>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (dt: string) => formatDateTime(dt),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: any, record: WorkflowListItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/workflows/${record.id}`)}
          >
            {record.is_builtin ? '查看/试运行' : '编排配置'}
          </Button>

          <Button
            type="link"
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => setSelectedWorkflowForRevision(record)}
          >
            版本
          </Button>

          {!record.is_builtin && !record.archived_at && (
            <Popconfirm
              title="确认归档此工作流？"
              description="归档后工作流将进入只读封存态，不再执行任何计划构建。"
              onConfirm={() => archiveMutation.mutate(record)}
              okText="确认归档"
              cancelText="取消"
            >
              <Button
                type="link"
                danger
                size="small"
                icon={<DeleteOutlined />}
                loading={archiveMutation.isPending}
              >
                归档
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            工作流编排中心 (Workflows)
          </Title>
          <Text type="secondary">
            针对复杂 NAS 规则与整理方案的一站式无损编排、版本管理与计划构建引擎
          </Text>
        </div>

        <Space>
          <Space>
            <Switch checked={includeArchived} onChange={setIncludeArchived} />
            <Text type="secondary">包含已归档</Text>
          </Space>

          <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
            刷新
          </Button>

          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => navigate('/workflows/new')}
          >
            新建工作流
          </Button>
        </Space>
      </div>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={workflows || []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          pagination={{ pageSize: 15 }}
        />
      </Card>

      {selectedWorkflowForRevision && (
        <RevisionDrawer
          open={!!selectedWorkflowForRevision}
          workflowId={selectedWorkflowForRevision.id}
          currentRevision={selectedWorkflowForRevision.current_revision}
          isBuiltin={selectedWorkflowForRevision.is_builtin}
          onClose={() => setSelectedWorkflowForRevision(null)}
          onRollbackSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
            refetch();
          }}
        />
      )}
    </div>
  );
};
