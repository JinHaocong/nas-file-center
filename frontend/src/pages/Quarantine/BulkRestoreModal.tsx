import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, List, Modal, Radio, Space, Tag, Typography, message } from 'antd';
import { UndoOutlined } from '@ant-design/icons';
import { quarantineApi } from '../../api/quarantine';
import {
  QuarantineBulkConflictPolicy,
  QuarantineBulkPlanResponse,
  QuarantineBulkPreviewResponse,
} from '../../types';
import {
  getBulkRestoreAvailability,
  isBulkPreviewSelectionCurrent,
} from '../../components/quarantine/quarantine_rules';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  entryIds: number[];
  isSafeMode: boolean;
  onClose: () => void;
  onPlanCreated: (plan: QuarantineBulkPlanResponse) => void;
}

export const BulkRestoreModal: React.FC<Props> = ({
  open,
  entryIds,
  isSafeMode,
  onClose,
  onPlanCreated,
}) => {
  const [policy, setPolicy] = useState<QuarantineBulkConflictPolicy>('skip');
  const [preview, setPreview] = useState<QuarantineBulkPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);

  const selectionKey = useMemo(() => [...entryIds].sort((a, b) => a - b).join(','), [entryIds]);
  const availability = getBulkRestoreAvailability(isSafeMode, policy);
  const previewCurrent = Boolean(
    preview &&
      preview.action === 'restore' &&
      preview.items.every((item) => item.conflict_policy === undefined || item.conflict_policy === policy) &&
      isBulkPreviewSelectionCurrent(preview.entry_ids, entryIds)
  );
  const canGenerate = Boolean(
    previewCurrent &&
      preview &&
      preview.blocked_count === 0 &&
      availability.canRestore &&
      !planLoading
  );

  useEffect(() => {
    if (open) {
      setPolicy('skip');
      setPreview(null);
      setPreviewLoading(false);
      setPlanLoading(false);
    }
  }, [open, selectionKey]);

  const handlePolicyChange = (value: QuarantineBulkConflictPolicy) => {
    setPolicy(value);
    setPreview(null);
  };

  const handlePreview = async () => {
    if (entryIds.length === 0) {
      message.warning('请先选择至少一个 active 隔离条目');
      return;
    }
    if (!availability.canRestore) {
      message.warning(availability.reason || '当前状态禁止批量恢复');
      return;
    }

    setPreviewLoading(true);
    setPreview(null);
    try {
      const result = await quarantineApi.bulkPreview({
        action: 'restore',
        entry_ids: [...entryIds],
        conflict_policy: policy,
      });
      setPreview(result);
      if (result.blocked_count > 0) {
        message.warning(`Preview 完成：${result.blocked_count} 个条目被安全阻断，不能生成 Draft`);
      } else {
        message.success(`Preview 完成：${result.eligible_count} 个条目可生成恢复 Draft`);
      }
    } catch (err: any) {
      message.error(err?.message || '批量恢复 Preview 失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleGenerateDraft = async () => {
    if (!preview || !previewCurrent) {
      message.warning('选择或策略已变化，请重新 Preview');
      setPreview(null);
      return;
    }
    if (preview.blocked_count > 0) {
      message.error('Preview 中存在 blocked 条目，按照 Gate6-A fail-closed 规则不能生成 Draft');
      return;
    }
    if (!availability.canRestore) {
      message.error(availability.reason || '当前状态禁止批量恢复');
      return;
    }

    setPlanLoading(true);
    try {
      const plan = await quarantineApi.bulkPlan({
        action: 'restore',
        entry_ids: [...preview.entry_ids],
        conflict_policy: policy,
        expected_preview_digest: preview.preview_digest,
      });
      message.success(`批量恢复 Draft #${plan.id} 已生成；尚未执行任何文件变更`);
      onPlanCreated(plan);
    } catch (err: any) {
      setPreview(null);
      message.error(err?.message || '生成批量恢复 Draft 失败；请重新 Preview');
    } finally {
      setPlanLoading(false);
    }
  };

  return (
    <Modal
      className="nfc-overlay-modal"
      title={
        <Space>
          <UndoOutlined style={{ color: '#1677ff' }} />
          <span>批量恢复 — 生成安全 Draft</span>
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
          disabled={!availability.canRestore || planLoading || entryIds.length === 0}
        >
          重新 Preview
        </Button>,
        <Button
          key="draft"
          type="primary"
          onClick={handleGenerateDraft}
          loading={planLoading}
          disabled={!canGenerate || previewLoading}
        >
          生成 Draft
        </Button>,
      ]}
      destroyOnClose
      width={680}
    >
      <Alert
        type="info"
        showIcon
        message={`已明确选择 ${entryIds.length} 个 active 条目`}
        description="此窗口只执行 Preview 与 Draft 生成，不会直接恢复文件。Draft 生成后仍必须经过 Plan 的 Freeze → Validate → Execute。"
        style={{ marginBottom: 16 }}
      />

      {isSafeMode && (
        <Alert
          type="warning"
          showIcon
          message="ALLOW_MUTATION=false"
          description="当前只读安全模式禁止生成可执行的批量恢复计划。"
          style={{ marginBottom: 16 }}
        />
      )}

      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 16 }}>
        <Text strong>冲突处理</Text>
        <Radio.Group
          value={policy}
          onChange={(event) => handlePolicyChange(event.target.value)}
          disabled={previewLoading || planLoading || isSafeMode}
        >
          <Space direction="vertical">
            <Radio value="skip">跳过（默认）— 目标已存在时保留隔离条目，不覆盖</Radio>
            <Radio value="rename">自动重命名 — 使用服务端冻结的安全目标，不覆盖</Radio>
          </Space>
        </Radio.Group>
      </Space>

      {!preview && (
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          先运行 Preview。任何 blocked 条目都会阻止整批 Draft 生成，不会静默丢弃成员。
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
        </Space>
      )}
    </Modal>
  );
};
