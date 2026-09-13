import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Input, List, Modal, Space, Tag, Typography, message } from 'antd';
import { DeleteOutlined, ExclamationCircleOutlined, LockOutlined } from '@ant-design/icons';
import { quarantineApi } from '../../api/quarantine';
import { QuarantineBulkPlanResponse, QuarantineBulkPreviewResponse } from '../../types';
import { isBulkPreviewSelectionCurrent } from '../../components/quarantine/quarantine_rules';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  entryIds: number[];
  isAdmin: boolean;
  allowMutation: boolean;
  allowDelete: boolean;
  onClose: () => void;
  onPlanCreated: (plan: QuarantineBulkPlanResponse) => void;
}

export const BulkPurgeModal: React.FC<Props> = ({
  open,
  entryIds,
  isAdmin,
  allowMutation,
  allowDelete,
  onClose,
  onPlanCreated,
}) => {
  const [confirmInput, setConfirmInput] = useState('');
  const [preview, setPreview] = useState<QuarantineBulkPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);

  const selectionKey = useMemo(() => [...entryIds].sort((a, b) => a - b).join(','), [entryIds]);
  const canPurge = isAdmin && allowMutation && allowDelete;
  const previewCurrent = Boolean(
    preview && preview.action === 'purge' && isBulkPreviewSelectionCurrent(preview.entry_ids, entryIds)
  );
  const isConfirmed = confirmInput === 'DELETE';
  const canGenerate = Boolean(
    canPurge &&
      isConfirmed &&
      previewCurrent &&
      preview &&
      preview.blocked_count === 0 &&
      !planLoading
  );

  useEffect(() => {
    if (open) {
      setConfirmInput('');
      setPreview(null);
      setPreviewLoading(false);
      setPlanLoading(false);
    }
  }, [open, selectionKey]);

  const handlePreview = async () => {
    if (entryIds.length === 0) {
      message.warning('请先选择至少一个 active 隔离条目');
      return;
    }
    if (!canPurge) {
      message.error('当前管理员权限或服务端安全开关禁止批量永久删除');
      return;
    }

    setPreviewLoading(true);
    setPreview(null);
    setConfirmInput('');
    try {
      const result = await quarantineApi.bulkPreview({
        action: 'purge',
        entry_ids: [...entryIds],
      });
      setPreview(result);
      if (result.blocked_count > 0) {
        message.warning(`Preview 完成：${result.blocked_count} 个条目被安全阻断，不能生成 Draft`);
      } else {
        message.success(`Preview 完成：${result.eligible_count} 个条目可进入永久删除 Draft`);
      }
    } catch (err: any) {
      message.error(err?.message || '批量永久删除 Preview 失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleGenerateDraft = async () => {
    if (!preview || !previewCurrent) {
      message.warning('选择或 Preview 身份已变化，请重新 Preview');
      setPreview(null);
      setConfirmInput('');
      return;
    }
    if (preview.blocked_count > 0) {
      message.error('Preview 中存在 blocked 条目，按照 Gate6-A fail-closed 规则不能生成 Draft');
      return;
    }
    if (!canPurge) {
      message.error('当前管理员权限或服务端安全开关禁止批量永久删除');
      return;
    }
    if (!isConfirmed) {
      message.error('必须严格输入全大写 DELETE 确认当前 digest-bound 批次');
      return;
    }

    setPlanLoading(true);
    try {
      const plan = await quarantineApi.bulkPlan({
        action: 'purge',
        entry_ids: [...preview.entry_ids],
        expected_preview_digest: preview.preview_digest,
        confirmation: 'DELETE',
      });
      message.success(`批量永久删除 Draft #${plan.id} 已生成；尚未删除任何文件`);
      onPlanCreated(plan);
    } catch (err: any) {
      setPreview(null);
      setConfirmInput('');
      message.error(err?.message || '生成批量永久删除 Draft 失败；请重新 Preview 并重新确认');
    } finally {
      setPlanLoading(false);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
          <span style={{ color: '#cf1322' }}>批量永久删除 — 生成安全 Draft</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose} disabled={previewLoading || planLoading}>
          取消
        </Button>,
        <Button
          key="preview"
          onClick={handlePreview}
          loading={previewLoading}
          disabled={!canPurge || planLoading || entryIds.length === 0}
        >
          重新 Preview
        </Button>,
        <Button
          key="draft"
          danger
          type="primary"
          icon={<DeleteOutlined />}
          onClick={handleGenerateDraft}
          loading={planLoading}
          disabled={!canGenerate || previewLoading}
        >
          生成永久删除 Draft
        </Button>,
      ]}
      destroyOnClose
      width={700}
    >
      {!isAdmin && (
        <Alert
          type="error"
          showIcon
          message="仅系统管理员允许批量永久删除"
          style={{ marginBottom: 12 }}
        />
      )}
      {!allowMutation && (
        <Alert
          type="warning"
          showIcon
          icon={<LockOutlined />}
          message="ALLOW_MUTATION=false"
          style={{ marginBottom: 12 }}
        />
      )}
      {!allowDelete && (
        <Alert
          type="warning"
          showIcon
          icon={<LockOutlined />}
          message="ALLOW_DELETE=false"
          style={{ marginBottom: 12 }}
        />
      )}

      <Alert
        type="error"
        showIcon
        message={`不可逆操作：已明确选择 ${entryIds.length} 个 active 条目`}
        description="此窗口不会立即删除文件；它只会为当前 Preview digest 生成 Draft。真正删除仍必须进入 Plan 页面执行 Freeze → Validate → Execute。执行后的永久删除不可撤销。"
        style={{ marginBottom: 16 }}
      />

      {!preview && (
        <Paragraph type="secondary">
          先运行 Preview。服务端会重新核验每个选中条目的状态、身份与 zfuse COMPAT purge topology；任一 blocked 成员都会阻止整批 Draft 生成。
        </Paragraph>
      )}

      {preview && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <Tag color="blue">Eligible {preview.eligible_count}</Tag>
            <Tag color={preview.blocked_count > 0 ? 'red' : 'green'}>Blocked {preview.blocked_count}</Tag>
            <Text type="secondary">Digest: {preview.preview_digest.slice(0, 16)}…</Text>
          </Space>

          {preview.blocked_count > 0 && (
            <List
              size="small"
              bordered
              dataSource={preview.items.filter((item) => !item.eligible)}
              renderItem={(item) => (
                <List.Item>
                  <Text type="danger">
                    #{item.entry_id}: {item.reason || 'blocked'}
                  </Text>
                </List.Item>
              )}
            />
          )}

          {preview.blocked_count === 0 && (
            <div style={{ background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 8, padding: 16 }}>
              <Paragraph style={{ marginBottom: 8, color: '#cf1322', fontWeight: 500 }}>
                Preview 已冻结当前批次。若确认要生成这个不可逆操作的 Draft，请输入大写{' '}
                <Text code strong style={{ color: '#cf1322' }}>DELETE</Text>：
              </Paragraph>
              <Input
                value={confirmInput}
                onChange={(event) => setConfirmInput(event.target.value)}
                placeholder="请输入 DELETE"
                disabled={!canPurge || planLoading}
                status={confirmInput && !isConfirmed ? 'error' : undefined}
                prefix={<DeleteOutlined style={{ color: '#ff4d4f' }} />}
              />
              {confirmInput && !isConfirmed && (
                <Text type="danger" style={{ display: 'block', marginTop: 4, fontSize: 12 }}>
                  必须严格输入全大写 DELETE
                </Text>
              )}
            </div>
          )}
        </Space>
      )}
    </Modal>
  );
};
