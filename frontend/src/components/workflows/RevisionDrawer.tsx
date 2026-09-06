import React, { useState } from 'react';
import {
  Drawer,
  Table,
  Button,
  Tag,
  Typography,
  Space,
  Modal,
  Popconfirm,
  message,
  Alert,
} from 'antd';
import { HistoryOutlined, RollbackOutlined, EyeOutlined, ExportOutlined } from '@ant-design/icons';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import { WorkflowRevisionResponse, WorkflowResponse } from '../../types/workflow';
import { formatDateTime } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
import { canRollbackWorkflow } from '../../utils/workflowRbac';

const { Text } = Typography;

interface RevisionDrawerProps {
  open: boolean;
  workflowId: number;
  currentRevision: number;
  isBuiltin?: boolean;
  isArchived?: boolean;
  onClose: () => void;
  onRollbackSuccess: (res: WorkflowResponse) => void;
}

export const RevisionDrawer: React.FC<RevisionDrawerProps> = ({
  open,
  workflowId,
  currentRevision,
  isBuiltin = false,
  isArchived = false,
  onClose,
  onRollbackSuccess,
}) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [inspectRevision, setInspectRevision] = useState<WorkflowRevisionResponse | null>(null);

  const {
    data: revisions,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['workflowRevisions', workflowId],
    queryFn: () => workflowApi.listRevisions(workflowId),
    enabled: open && !!workflowId,
  });

  const rollbackMutation = useMutation({
    mutationFn: (targetRevision: number) =>
      workflowApi.rollbackWorkflow(workflowId, {
        target_revision: targetRevision,
        expected_current_revision: currentRevision,
      }),
    onSuccess: (data) => {
      message.success(`已成功回滚至版本 r${data.current_revision}`);
      refetch();
      onRollbackSuccess(data);
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '回滚失败');
    },
  });

  const columns = [
    {
      title: '版本号',
      dataIndex: 'revision',
      key: 'revision',
      width: 90,
      render: (rev: number) => (
        <Space>
          <Text strong>r{rev}</Text>
          {rev === currentRevision && <Tag color="blue">当前生效</Tag>}
        </Space>
      ),
    },
    {
      title: 'SHA256 校验和',
      dataIndex: 'definition_sha256',
      key: 'definition_sha256',
      ellipsis: true,
      render: (sha: string) => (
        <Text code copyable={{ text: sha }}>
          {sha ? `${sha.slice(0, 10)}...${sha.slice(-6)}` : '-'}
        </Text>
      ),
    },
    {
      title: '修改时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (dt: string) => formatDateTime(dt),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: any, record: WorkflowRevisionResponse) => {
        const isCurrent = record.revision === currentRevision;
        const canRollback = !isBuiltin && !isCurrent && canRollbackWorkflow(user?.role, isArchived);
        return (
          <Space>
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => setInspectRevision(record)}
            >
              查看定义
            </Button>

            {!isCurrent && (
              <Button
                size="small"
                icon={<ExportOutlined />}
                onClick={() => {
                  onClose();
                  navigate(`/workflows/${workflowId}?revision=${record.revision}`);
                }}
              >
                跳转查看
              </Button>
            )}

            {canRollback && (
              <Popconfirm
                title="确认回滚至该历史版本？"
                description={`系统将生成新修订版本并恢复至第 r${record.revision} 版定义。`}
                onConfirm={() => rollbackMutation.mutate(record.revision)}
                okText="确认回滚"
                cancelText="取消"
              >
                <Button
                  size="small"
                  type="link"
                  danger
                  icon={<RollbackOutlined />}
                  loading={rollbackMutation.isPending}
                >
                  回滚
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Drawer
        title={
          <Space>
            <HistoryOutlined />
            <span>版本历史与审计 (Workflow #{workflowId})</span>
          </Space>
        }
        open={open}
        onClose={onClose}
        width={720}
      >
        {isError && (
          <Alert
            type="error"
            message="获取版本历史失败"
            description={getStructuredApiError(error).message}
            style={{ marginBottom: 16 }}
          />
        )}

        <Table
          dataSource={revisions || []}
          columns={columns}
          rowKey="revision"
          loading={isLoading}
          pagination={false}
          size="small"
        />
      </Drawer>

      <Modal
        title={`工作流定义详情 (r${inspectRevision?.revision})`}
        open={!!inspectRevision}
        onCancel={() => setInspectRevision(null)}
        footer={[
          <Button key="close" onClick={() => setInspectRevision(null)}>
            关闭
          </Button>,
        ]}
        width={680}
      >
        {inspectRevision && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">Definition SHA256: </Text>
              <Text code copyable>{inspectRevision.definition_sha256}</Text>
            </div>
            <pre
              style={{
                background: '#f5f5f5',
                padding: 12,
                borderRadius: 6,
                maxHeight: 400,
                overflow: 'auto',
                fontSize: 12,
              }}
            >
              {JSON.stringify(inspectRevision.definition, null, 2)}
            </pre>
          </div>
        )}
      </Modal>
    </>
  );
};
