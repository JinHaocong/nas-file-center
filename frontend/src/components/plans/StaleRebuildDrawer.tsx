import React, { useState, useEffect } from 'react';
import {
  Drawer,
  Button,
  Space,
  Table,
  Tag,
  Alert,
  Spin,
  Typography,
  Input,
  message,
  Card,
  Descriptions,
} from 'antd';
import {
  ReloadOutlined,
  BuildOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError, formatDedupeErrorMessage } from '../../api/errors';
import { WorkflowPreviewItem } from '../../types/workflow';
import { computeRebuildReadiness } from '../../utils/rebuildReadiness';

const { Text } = Typography;

interface StaleRebuildDrawerProps {
  open: boolean;
  planId: number;
  onClose: () => void;
  onRebuildSuccess: (newPlanId: number) => void;
}

export const StaleRebuildDrawer: React.FC<StaleRebuildDrawerProps> = ({
  open,
  planId,
  onClose,
  onRebuildSuccess,
}) => {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [customPlanName, setCustomPlanName] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewInvalidated, setPreviewInvalidated] = useState(false);
  const [acceptedDigest, setAcceptedDigest] = useState<string | null>(null);

  const {
    data: preview,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['rebuildPlanPreview', planId, page, pageSize],
    queryFn: () =>
      workflowApi.rebuildPlanPreview(planId, {
        page,
        page_size: pageSize,
      }),
    enabled: open && !!planId,
  });

  useEffect(() => {
    if (preview?.compile_digest && !previewInvalidated) {
      setAcceptedDigest(preview.compile_digest);
    }
  }, [preview, previewInvalidated]);

  const handleManualRefresh = async () => {
    setErrorMessage(null);
    setPreviewInvalidated(true);
    setAcceptedDigest(null);
    try {
      const res = await refetch();
      if (res.isSuccess && res.data?.compile_digest) {
        setAcceptedDigest(res.data.compile_digest);
        setPreviewInvalidated(false);
      } else {
        setPreviewInvalidated(true);
        setAcceptedDigest(null);
      }
    } catch {
      setPreviewInvalidated(true);
      setAcceptedDigest(null);
    }
  };

  const readiness = computeRebuildReadiness({
    hasPreview: Boolean(preview),
    previewInvalidated,
    acceptedDigest,
    isLoading,
    isFetching,
  });

  const rebuildMutation = useMutation({
    mutationFn: async () => {
      if (!readiness.canSubmit || !readiness.submitDigest) {
        throw new Error('当前预览已失效或正在获取，请先点击“刷新预览”重新获取有效摘要');
      }
      return workflowApi.rebuildPlan(planId, {
        expected_compile_digest: readiness.submitDigest,
        plan_name: customPlanName.trim() || undefined,
      });
    },
    onSuccess: (data) => {
      message.success(`全新重建草稿计划 #${data.id || data.plan_id} 创建成功`);
      onClose();
      onRebuildSuccess(data.id || data.plan_id);
    },
    onError: (err: unknown) => {
      const structured = getStructuredApiError(err);
      if (structured.code === 'PREVIEW_CHANGED') {
        setPreviewInvalidated(true);
        setAcceptedDigest(null);
        setErrorMessage('文件状态或底层快照已发生变动，旧预览已失效，必须手动点击“刷新预览”重新计算摘要');
      } else if (structured.code === 'WORKFLOW_ARCHIVED') {
        setErrorMessage('关联的工作流已被归档，无法重新生成计划');
      } else if (structured.code === 'DEDUPE_RESCAN_REQUIRED') {
        setErrorMessage(formatDedupeErrorMessage(err));
      } else {
        setErrorMessage(structured.message || '重建计划失败');
      }
    },
  });

  const columns = [
    {
      title: '序号',
      key: 'index',
      width: 60,
      render: (_: any, __: any, idx: number) => (page - 1) * pageSize + idx + 1,
    },
    {
      title: '操作类型',
      dataIndex: 'operation',
      key: 'operation',
      width: 100,
      render: (op: string) => {
        const colors: Record<string, string> = {
          rename: 'cyan',
          move: 'purple',
          touch: 'blue',
          quarantine: 'orange',
        };
        return <Tag color={colors[op] || 'default'}>{op}</Tag>;
      },
    },
    {
      title: '变更状态',
      dataIndex: 'changed',
      key: 'changed',
      width: 100,
      render: (changed: boolean) =>
        changed ? <Tag color="processing">有变更</Tag> : <Tag color="default">保持/更新</Tag>,
    },
    {
      title: '源文件路径',
      dataIndex: 'source_path',
      key: 'source_path',
      ellipsis: true,
    },
    {
      title: '目标文件路径',
      dataIndex: 'target_path',
      key: 'target_path',
      ellipsis: true,
      render: (target: string | null, record: WorkflowPreviewItem) => {
        if (record.operation === 'touch') {
          return (
            <Text type="secondary">
              刷新时间戳 (mtime): {record.mtime_ns ? new Date(record.mtime_ns / 1e6).toLocaleString() : '当前时间'}
            </Text>
          );
        }
        return target || <Text type="secondary">-</Text>;
      },
    },
  ];

  return (
    <Drawer
      title={
        <Space>
          <BuildOutlined />
          <span>过期工作流计划重建预览 (Rebuild Stale Plan #{planId})</span>
        </Space>
      }
      open={open}
      onClose={onClose}
      width={900}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={handleManualRefresh} loading={isLoading || isFetching}>
            刷新预览
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={rebuildMutation.isPending}
            disabled={!readiness.canSubmit}
            onClick={() => rebuildMutation.mutate()}
          >
            生成全新草稿 (Rebuild as Draft)
          </Button>
        </Space>
      }
    >
      {previewInvalidated && (
        <Alert
          type="warning"
          showIcon
          message="预览摘要已失效"
          description="底层状态发生变动，旧编译摘要已被废弃，无法提交重建。请点击上方“刷新预览”以生成最新有效摘要。"
          style={{ marginBottom: 16 }}
        />
      )}

      {errorMessage && (
        <Alert
          type="error"
          showIcon
          message="重建操作受阻"
          description={errorMessage}
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setErrorMessage(null)}
        />
      )}

      {isError && (
        <Alert
          type="error"
          showIcon
          message="无法生成重建预览"
          description={getStructuredApiError(error).message}
          style={{ marginBottom: 16 }}
        />
      )}

      {isLoading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="正在基于权威 Lineage 与快照计算全新预览..." />
        </div>
      )}

      {preview && (
        <>
          <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="关联工作流 ID">
                #{preview.workflow_id}
              </Descriptions.Item>
              <Descriptions.Item label="工作流基线版本 (Lineage Revision)">
                第 r{preview.workflow_revision} 版
              </Descriptions.Item>
              <Descriptions.Item label="计划操作总项数">
                <Text strong style={{ color: '#1677ff' }}>
                  {preview.planned_operations_count} 项
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="匹配文件/目录数">
                {preview.matched_count} 项
              </Descriptions.Item>
              <Descriptions.Item label="编译摘要 (Compile Digest)" span={2}>
                <Text code copyable style={{ fontSize: 12 }}>
                  {preview.compile_digest}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="Definition SHA256" span={2}>
                <Text code copyable style={{ fontSize: 12 }}>
                  {preview.definition_sha256}
                </Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary">计划操作项全量预览 (含保持/更新与变更)</Text>

            <Input
              placeholder="自定义新重建草稿名称（可选）"
              value={customPlanName}
              onChange={(e) => setCustomPlanName(e.target.value)}
              style={{ width: 280 }}
            />
          </div>

          <Table
            dataSource={preview.items}
            columns={columns}
            rowKey={(rec, idx) => `${rec.source_path}-${rec.operation}-${idx}`}
            size="small"
            pagination={{
              current: page,
              pageSize,
              total: preview.planned_operations_count,
              showSizeChanger: true,
              pageSizeOptions: ['20', '50', '100'],
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        </>
      )}
    </Drawer>
  );
};
