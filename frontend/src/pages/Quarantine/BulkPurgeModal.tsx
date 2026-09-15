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
      message.error('Preview 中存在 blocked 条目，按照 fail-closed 规则不能生成 Draft');
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
      width={760}
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
        description="此窗口只生成当前 Preview digest 对应的 Draft。真正执行仍必须经过 Freeze → Validate → Execute。执行语义是普通文件删除（unlink）：只移除 NFC 拥有并已冻结的隔离区路径，不覆盖文件内容，也不承诺安全擦除。"
        style={{ marginBottom: 16 }}
      />

      {!preview && (
        <Paragraph type="secondary">
          先运行 Preview。服务端会重新核验每个选中条目的状态、持久化身份与 unlink_v1 pathname authority；任一 mutation blocker 都会阻止整批 Draft。索引范围内的 hard link 与同内容独立副本仅作为 advisory，不会扩大或改变删除权限。
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
                    {item.mutation_blockers?.length ? ` (${item.mutation_blockers.join(', ')})` : ''}
                  </Text>
                </List.Item>
              )}
            />
          )}

          {preview.items
            .filter((item) => item.eligible && item.purge_semantics === 'unlink_v1')
            .map((item) => (
              <div key={item.entry_id} style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 12 }}>
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Text strong>#{item.entry_id} · 普通文件删除（unlink_v1）</Text>
                  {item.survivor_status === 'found' ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="当前隔离副本可清除，但索引范围内仍发现存活 hard link"
                      description={
                        <List
                          size="small"
                          dataSource={item.hardlink_survivor_paths || []}
                          renderItem={(path) => <List.Item><Text code>{path}</Text></List.Item>}
                        />
                      }
                    />
                  ) : item.survivor_status === 'incomplete' ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="索引范围内 hard link 检查不完整"
                      description={(item.advisory_diagnostics || []).join('; ') || '部分候选路径无法完成 live lstat 核验；这只是 advisory，不改变当前 unlink 权限。'}
                    />
                  ) : (
                    <Alert
                      type="success"
                      showIcon
                      message="索引范围内未发现存活 hard link"
                      description={`检查范围：${item.survivor_scope || 'indexed_roots_only'}`}
                    />
                  )}

                  {(item.independent_copy_paths?.length || 0) > 0 && (
                    <Alert
                      type="info"
                      showIcon
                      message="发现同内容但不同 inode 的独立副本"
                      description={
                        <List
                          size="small"
                          dataSource={item.independent_copy_paths || []}
                          renderItem={(path) => <List.Item><Text code>{path}</Text></List.Item>}
                        />
                      }
                    />
                  )}
                </Space>
              </div>
            ))}

          {preview.blocked_count === 0 && (
            <div style={{ background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 8, padding: 16 }}>
              <Paragraph style={{ marginBottom: 8, color: '#cf1322', fontWeight: 500 }}>
                Preview 已冻结当前批次。hard-link survivor / 独立副本只是提示，不属于 mutation authority。若确认生成 Draft，请输入大写{' '}
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
