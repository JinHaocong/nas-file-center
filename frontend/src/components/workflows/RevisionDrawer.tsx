import React, { useState } from 'react';
import {
  Alert,
  Button,
  Drawer,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { ExportOutlined, EyeOutlined, HistoryOutlined, RollbackOutlined } from '@ant-design/icons';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import { WorkflowRevisionResponse, WorkflowResponse } from '../../types/workflow';
import { formatDateTime } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
import { canRollbackWorkflow } from '../../utils/workflowRbac';
import { useResponsive } from '../../hooks/useResponsive';

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
  const { isMobile } = useResponsive();
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

  const canRollbackRevision = (record: WorkflowRevisionResponse) =>
    !isBuiltin &&
    record.revision !== currentRevision &&
    canRollbackWorkflow(user?.role, isArchived);

  const jumpToRevision = (revision: number) => {
    onClose();
    navigate(`/workflows/${workflowId}?revision=${revision}`);
  };

  const columns = [
    {
      title: '版本',
      dataIndex: 'revision',
      key: 'revision',
      width: 110,
      render: (rev: number) => (
        <Space>
          <Text strong>r{rev}</Text>
          {rev === currentRevision && <Tag color="blue">当前</Tag>}
        </Space>
      ),
    },
    {
      title: 'Definition SHA256',
      dataIndex: 'definition_sha256',
      key: 'definition_sha256',
      ellipsis: true,
      render: (sha: string) => (
        <Text code copyable={{ text: sha }}>
          {sha ? `${sha.slice(0, 10)}…${sha.slice(-6)}` : '—'}
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
      render: (_: unknown, record: WorkflowRevisionResponse) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => setInspectRevision(record)}>
            查看
          </Button>
          {record.revision !== currentRevision && (
            <Button size="small" icon={<ExportOutlined />} onClick={() => jumpToRevision(record.revision)}>
              跳转
            </Button>
          )}
          {canRollbackRevision(record) && (
            <Popconfirm
              title="确认回滚至该历史版本？"
              description={`系统将生成新修订版本并恢复至第 r${record.revision} 版定义。`}
              onConfirm={() => rollbackMutation.mutate(record.revision)}
              okText="确认回滚"
              cancelText="取消"
            >
              <Button
                size="small"
                danger
                icon={<RollbackOutlined />}
                loading={rollbackMutation.isPending}
              >
                回滚
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const revisionItems = revisions || [];

  return (
    <>
      <Drawer
        rootClassName="nfc-overlay-drawer nfc-revision-drawer"
        title={
          <div className="nfc-drawer-title">
            <span className="nfc-drawer-title-kicker">Revision history</span>
            <div className="nfc-drawer-title-row">
              <HistoryOutlined />
              <span>Workflow #{workflowId}</span>
            </div>
          </div>
        }
        open={open}
        onClose={onClose}
        width={760}
      >
        {isError && (
          <Alert
            className="nfc-overlay-alert"
            type="error"
            message="获取版本历史失败"
            description={getStructuredApiError(error).message}
          />
        )}

        {isMobile ? (
          <div className="nfc-revision-mobile-list">
            {revisionItems.map((record) => (
              <article className="nfc-revision-mobile-card" key={record.revision}>
                <div className="nfc-revision-mobile-topline">
                  <div>
                    <strong>r{record.revision}</strong>
                    {record.revision === currentRevision && <Tag color="blue">当前</Tag>}
                  </div>
                  <time>{formatDateTime(record.created_at)}</time>
                </div>
                <Text code copyable={{ text: record.definition_sha256 }}>
                  {record.definition_sha256
                    ? `${record.definition_sha256.slice(0, 12)}…${record.definition_sha256.slice(-8)}`
                    : '—'}
                </Text>
                <div className="nfc-mobile-record-actions">
                  <Button size="small" icon={<EyeOutlined />} onClick={() => setInspectRevision(record)}>
                    查看定义
                  </Button>
                  {record.revision !== currentRevision && (
                    <Button size="small" icon={<ExportOutlined />} onClick={() => jumpToRevision(record.revision)}>
                      跳转
                    </Button>
                  )}
                  {canRollbackRevision(record) && (
                    <Popconfirm
                      title="确认回滚至该历史版本？"
                      onConfirm={() => rollbackMutation.mutate(record.revision)}
                      okText="确认回滚"
                      cancelText="取消"
                    >
                      <Button size="small" danger icon={<RollbackOutlined />}>
                        回滚
                      </Button>
                    </Popconfirm>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Table
            className="nfc-embedded-table"
            dataSource={revisionItems}
            columns={columns}
            rowKey="revision"
            loading={isLoading}
            pagination={false}
            size="small"
          />
        )}
      </Drawer>

      <Modal
        className="nfc-overlay-modal nfc-definition-modal"
        title={`工作流定义 · r${inspectRevision?.revision || '—'}`}
        open={!!inspectRevision}
        onCancel={() => setInspectRevision(null)}
        footer={[
          <Button key="close" onClick={() => setInspectRevision(null)}>
            关闭
          </Button>,
        ]}
        width={720}
      >
        {inspectRevision && (
          <div className="nfc-definition-inspector">
            <div className="nfc-definition-sha">
              <span>Definition SHA256</span>
              <Text code copyable>{inspectRevision.definition_sha256}</Text>
            </div>
            <pre className="nfc-code-block nfc-code-block-large">
              {JSON.stringify(inspectRevision.definition, null, 2)}
            </pre>
          </div>
        )}
      </Modal>
    </>
  );
};
