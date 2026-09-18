import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Input,
  Pagination,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  BuildOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import { WorkflowPreviewItem } from '../../types/workflow';
import { computeRebuildReadiness } from '../../utils/rebuildReadiness';
import { useResponsive } from '../../hooks/useResponsive';

const { Text } = Typography;

interface StaleRebuildDrawerProps {
  open: boolean;
  planId: number;
  onClose: () => void;
  onRebuildSuccess: (newPlanId: number) => void;
}

const operationTone: Record<string, string> = {
  rename: 'cyan',
  move: 'purple',
  touch: 'blue',
  quarantine: 'orange',
};

export const StaleRebuildDrawer: React.FC<StaleRebuildDrawerProps> = ({
  open,
  planId,
  onClose,
  onRebuildSuccess,
}) => {
  const { isMobile } = useResponsive();
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
        throw new Error('当前预览已失效或正在获取，请先刷新预览');
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
        setErrorMessage('文件状态或底层快照已变化，请重新刷新预览。');
      } else if (structured.code === 'WORKFLOW_ARCHIVED') {
        setErrorMessage('关联工作流已归档，无法重新生成计划。');
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
      render: (_: unknown, __: unknown, idx: number) => (page - 1) * pageSize + idx + 1,
    },
    {
      title: '操作',
      dataIndex: 'operation',
      key: 'operation',
      width: 100,
      render: (op: string) => <Tag color={operationTone[op] || 'default'}>{op}</Tag>,
    },
    {
      title: '变更',
      dataIndex: 'changed',
      key: 'changed',
      width: 100,
      render: (changed: boolean) =>
        changed ? <Tag color="processing">有变更</Tag> : <Tag>保持/更新</Tag>,
    },
    {
      title: '源路径',
      dataIndex: 'source_path',
      key: 'source_path',
      ellipsis: true,
      render: (path: string) => <Text code>{path}</Text>,
    },
    {
      title: '目标路径',
      dataIndex: 'target_path',
      key: 'target_path',
      ellipsis: true,
      render: (target: string | null, record: WorkflowPreviewItem) => {
        if (record.operation === 'touch') {
          return (
            <Text type="secondary">
              mtime → {record.mtime_ns ? new Date(record.mtime_ns / 1e6).toLocaleString() : '当前时间'}
            </Text>
          );
        }
        return target ? <Text code>{target}</Text> : <Text type="secondary">—</Text>;
      },
    },
  ];

  const items = preview?.items || [];

  return (
    <Drawer
      rootClassName="nfc-overlay-drawer nfc-stale-rebuild-drawer"
      title={
        <div className="nfc-drawer-title">
          <span className="nfc-drawer-title-kicker">Rebuild preview</span>
          <div className="nfc-drawer-title-row">
            <BuildOutlined />
            <span>过期计划 #{planId}</span>
          </div>
        </div>
      }
      open={open}
      onClose={onClose}
      width={940}
      extra={
        <div className="nfc-drawer-actions">
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
            生成草稿
          </Button>
        </div>
      }
    >
      <div className="nfc-overlay-stack">
        {previewInvalidated && (
          <Alert
            className="nfc-overlay-alert"
            type="warning"
            showIcon
            message="预览摘要已失效"
            description="底层状态已变化，旧编译摘要不能提交。请刷新预览获取新的 digest。"
          />
        )}

        {errorMessage && (
          <Alert
            className="nfc-overlay-alert"
            type="error"
            showIcon
            message="重建操作受阻"
            description={errorMessage}
            closable
            onClose={() => setErrorMessage(null)}
          />
        )}

        {isError && (
          <Alert
            className="nfc-overlay-alert"
            type="error"
            showIcon
            message="无法生成重建预览"
            description={formatDedupeErrorMessage(error)}
          />
        )}

        {isLoading && (
          <div className="nfc-overlay-loading">
            <Spin tip="正在基于权威 Lineage 与快照计算预览..." />
          </div>
        )}

        {preview && (
          <>
            <section className="nfc-overlay-section">
              <header className="nfc-overlay-section-header">
                <div>
                  <span>Authority</span>
                  <h3>重建基线</h3>
                </div>
              </header>
              <Descriptions
                className="nfc-detail-descriptions"
                size="small"
                column={{ xxl: 2, xl: 2, lg: 2, md: 1, sm: 1, xs: 1 }}
              >
                <Descriptions.Item label="工作流">#{preview.workflow_id}</Descriptions.Item>
                <Descriptions.Item label="Lineage Revision">r{preview.workflow_revision}</Descriptions.Item>
                <Descriptions.Item label="计划项">
                  <Text strong>{preview.planned_operations_count}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="匹配对象">{preview.matched_count}</Descriptions.Item>
                <Descriptions.Item label="Compile Digest" span={2}>
                  <Text code copyable>{preview.compile_digest}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="Definition SHA256" span={2}>
                  <Text code copyable>{preview.definition_sha256}</Text>
                </Descriptions.Item>
              </Descriptions>
            </section>

            <section className="nfc-overlay-section nfc-overlay-section-flush">
              <header className="nfc-overlay-section-header nfc-overlay-section-header-actions">
                <div>
                  <span>Operations</span>
                  <h3>计划操作预览</h3>
                </div>
                <Input
                  className="nfc-rebuild-name-input"
                  placeholder="自定义新草稿名称（可选）"
                  value={customPlanName}
                  onChange={(e) => setCustomPlanName(e.target.value)}
                />
              </header>

              {isMobile ? (
                <div className="nfc-rebuild-mobile-list">
                  {items.map((item, idx) => (
                    <article className="nfc-rebuild-mobile-card" key={`${item.source_path}-${item.operation}-${idx}`}>
                      <div className="nfc-rebuild-mobile-topline">
                        <Tag color={operationTone[item.operation] || 'default'}>{item.operation}</Tag>
                        {item.changed ? <Tag color="processing">有变更</Tag> : <Tag>保持/更新</Tag>}
                      </div>
                      <div className="nfc-rebuild-mobile-paths">
                        <Text code>{item.source_path}</Text>
                        <span>→</span>
                        <Text code>{item.target_path || '—'}</Text>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <Table
                  className="nfc-embedded-table"
                  dataSource={items}
                  columns={columns}
                  rowKey={(rec, idx) => `${rec.source_path}-${rec.operation}-${idx}`}
                  size="small"
                  pagination={false}
                />
              )}

              <Pagination
                className="nfc-embedded-pagination"
                current={page}
                pageSize={pageSize}
                total={preview.planned_operations_count}
                showSizeChanger={!isMobile}
                pageSizeOptions={['20', '50', '100']}
                simple={isMobile}
                onChange={(p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                }}
              />
            </section>
          </>
        )}
      </div>
    </Drawer>
  );
};
