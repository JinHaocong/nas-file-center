import React, { useMemo, useState } from 'react';
import {
  Button,
  Empty,
  Pagination,
  Popconfirm,
  Switch,
  Table,
  message,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import { WorkflowListItem } from '../../types/workflow';
import { RevisionDrawer } from '../../components/workflows/RevisionDrawer';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
import { canArchiveWorkflow, canCreateWorkflow, canPermanentlyDeleteWorkflow } from '../../utils/workflowRbac';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';

const modeLabel = (mode: WorkflowListItem['mode']) => {
  if (mode === 'dedupe') return '高级去重流';
  if (mode === 'organizer') return '目录整理流';
  if (mode === 'utility') return '目录工具流';
  return '文件规则流';
};

export const WorkflowListPage: React.FC = () => {
  useTitle('工作流中心');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();

  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedWorkflowForRevision, setSelectedWorkflowForRevision] = useState<WorkflowListItem | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 15;

  const { data: workflows, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['workflowsList', includeArchived],
    queryFn: () => workflowApi.listWorkflows(includeArchived),
  });

  const archiveMutation = useMutation({
    mutationFn: (workflow: WorkflowListItem) =>
      workflowApi.archiveWorkflow(workflow.id, workflow.current_revision),
    onSuccess: () => {
      message.success('工作流已成功归档');
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      refetch();
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '归档失败');
    },
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: (workflow: WorkflowListItem) =>
      workflowApi.permanentlyDeleteWorkflow(workflow.id, workflow.current_revision),
    onSuccess: (_, workflow) => {
      message.success(`工作流「${workflow.name}」及其版本历史已彻底删除`);
      if (selectedWorkflowForRevision?.id === workflow.id) {
        setSelectedWorkflowForRevision(null);
      }
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      refetch();
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '彻底删除工作流失败');
    },
  });

  const items = workflows || [];
  const mobileItems = useMemo(
    () => items.slice((page - 1) * pageSize, page * pageSize),
    [items, page]
  );

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 72,
      render: (id: number) => <span className="nfc-mono">#{id}</span>,
    },
    {
      title: '工作流',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: WorkflowListItem) => (
        <button
          type="button"
          className="nfc-workflow-name"
          onClick={() => navigate(`/workflows/${record.id}`)}
        >
          <strong>{name}</strong>
          {record.description && <span>{record.description}</span>}
        </button>
      ),
    },
    {
      title: '模式',
      dataIndex: 'mode',
      key: 'mode',
      width: 130,
      render: (mode: WorkflowListItem['mode']) => (
        <span className="nfc-kind-badge">{modeLabel(mode)}</span>
      ),
    },
    {
      title: '版本',
      dataIndex: 'current_revision',
      key: 'current_revision',
      width: 84,
      render: (revision: number) => <span className="nfc-mono">r{revision}</span>,
    },
    {
      title: '类别',
      dataIndex: 'is_builtin',
      key: 'is_builtin',
      width: 98,
      render: (builtin: boolean) => (
        <span className="nfc-kind-badge">{builtin ? 'builtin' : 'user'}</span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'archived_at',
      key: 'archived_at',
      width: 108,
      render: (archived: string | null) => (
        <StatusBadge
          status={archived ? 'stale' : 'completed'}
          label={archived ? '已归档' : '启用中'}
        />
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => <span className="nfc-table-meta">{formatDateTime(value)}</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 230,
      render: (_: unknown, record: WorkflowListItem) => (
        <div className="nfc-row-actions">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/workflows/${record.id}`)}
          >
            {record.is_builtin ? '查看/试运行' : '编排配置'}
          </Button>
          <Button
            type="text"
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => setSelectedWorkflowForRevision(record)}
          >
            版本
          </Button>
          {!record.is_builtin &&
            !record.archived_at &&
            canArchiveWorkflow(user?.role, Boolean(record.archived_at)) && (
              <Popconfirm
                title="确认归档此工作流？"
                description="归档后工作流进入只读封存态，不再执行任何计划构建。"
                onConfirm={() => archiveMutation.mutate(record)}
                okText="确认归档"
                cancelText="取消"
              >
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  loading={archiveMutation.isPending}
                >
                  归档
                </Button>
              </Popconfirm>
            )}
          {canPermanentlyDeleteWorkflow(user?.role, Boolean(record.archived_at), record.is_builtin) && (
            <Popconfirm
              title="彻底删除此已归档工作流？"
              description="工作流定义和全部修订版本将从数据库删除。若仍有可执行计划依赖，服务端会拒绝本操作。"
              onConfirm={() => permanentDeleteMutation.mutate(record)}
              okText="彻底删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
            >
              <Button
                type="text"
                danger
                size="small"
                icon={<DeleteOutlined />}
                loading={permanentDeleteMutation.isPending}
              >
                彻底删除
              </Button>
            </Popconfirm>
          )}
        </div>
      ),
    },
  ];

  const renderMobileActions = (record: WorkflowListItem) => (
    <div className="nfc-mobile-record-actions">
      <Button type="text" onClick={() => navigate(`/workflows/${record.id}`)}>
        {record.is_builtin ? '查看/试运行' : '编排配置'}
      </Button>
      <Button type="text" onClick={() => setSelectedWorkflowForRevision(record)}>
        版本历史
      </Button>
      {!record.is_builtin &&
        !record.archived_at &&
        canArchiveWorkflow(user?.role, Boolean(record.archived_at)) && (
          <Popconfirm
            title="确认归档此工作流？"
            description="归档后工作流进入只读封存态。"
            onConfirm={() => archiveMutation.mutate(record)}
            okText="归档"
            cancelText="取消"
          >
            <Button type="text" danger>归档</Button>
          </Popconfirm>
        )}
      {canPermanentlyDeleteWorkflow(user?.role, Boolean(record.archived_at), record.is_builtin) && (
        <Popconfirm
          title="彻底删除此已归档工作流？"
          description="会删除工作流定义和全部版本历史；活动计划存在时服务端会阻止。"
          onConfirm={() => permanentDeleteMutation.mutate(record)}
          okText="彻底删除"
          okButtonProps={{ danger: true }}
          cancelText="取消"
        >
          <Button type="text" danger loading={permanentDeleteMutation.isPending}>彻底删除</Button>
        </Popconfirm>
      )}
    </div>
  );

  return (
    <div className="nfc-operations-page nfc-workflows-page">
      <PageHeader
        eyebrow="Automation workflows"
        title="工作流编排中心"
        description="以版本化定义编排 NAS 文件规则、目录整理、高级去重和目录工具；Preview 与 Draft 都不会直接执行文件操作。"
        actions={
          <ActionBar compact>
            <label className="nfc-inline-switch">
              <Switch
                size="small"
                checked={includeArchived}
                onChange={(checked) => {
                  setIncludeArchived(checked);
                  setPage(1);
                }}
              />
              <span>包含已归档</span>
            </label>
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>
              刷新
            </Button>
            {canCreateWorkflow(user?.role) && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/workflows/new')}>
                新建工作流
              </Button>
            )}
          </ActionBar>
        }
      />

      <DataPanel
        title="工作流定义"
        description="工作流保存为修订版本；内置与归档定义保持只读。"
        action={<span className="nfc-panel-count">{items.length} workflows</span>}
        className="nfc-panel-flush"
        variant="dense"
      >
        <ResponsiveDataView
          desktop={
            <Table
              dataSource={items}
              columns={columns}
              rowKey="id"
              loading={isLoading}
              pagination={{ pageSize }}
            />
          }
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {mobileItems.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工作流" />
                ) : (
                  mobileItems.map((workflow) => (
                    <article className="nfc-workflow-mobile-card" key={workflow.id}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-plan-mobile-heading-copy">
                          <button
                            type="button"
                            className="nfc-mobile-record-title"
                            onClick={() => navigate(`/workflows/${workflow.id}`)}
                          >
                            {workflow.name}
                          </button>
                          <div className="nfc-inline-badges">
                            <span className="nfc-kind-badge">{modeLabel(workflow.mode)}</span>
                            <span className="nfc-kind-badge">
                              {workflow.is_builtin ? 'builtin' : 'user'}
                            </span>
                          </div>
                        </div>
                        <StatusBadge
                          status={workflow.archived_at ? 'stale' : 'completed'}
                          label={workflow.archived_at ? '已归档' : '启用中'}
                        />
                      </div>
                      {workflow.description && (
                        <p className="nfc-mobile-record-note">{workflow.description}</p>
                      )}
                      <div className="nfc-mobile-record-facts">
                        <span>版本 <b className="nfc-mono">r{workflow.current_revision}</b></span>
                        <span>更新 <b>{formatDateTime(workflow.updated_at)}</b></span>
                      </div>
                      {renderMobileActions(workflow)}
                    </article>
                  ))
                )}
              </div>
              <div className="nfc-mobile-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={items.length}
                  showSizeChanger={false}
                  onChange={setPage}
                />
              </div>
            </>
          }
        />
      </DataPanel>

      {selectedWorkflowForRevision && (
        <RevisionDrawer
          open={Boolean(selectedWorkflowForRevision)}
          workflowId={selectedWorkflowForRevision.id}
          currentRevision={selectedWorkflowForRevision.current_revision}
          isBuiltin={selectedWorkflowForRevision.is_builtin}
          isArchived={Boolean(selectedWorkflowForRevision.archived_at)}
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
