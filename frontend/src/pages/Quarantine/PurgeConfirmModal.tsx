import React, { useState, useEffect } from 'react';
import {
  Modal,
  Input,
  Typography,
  Descriptions,
  Alert,
  List,
  message,
  Space,
} from 'antd';
import { DeleteOutlined, ExclamationCircleOutlined, LockOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quarantineApi } from '../../api/quarantine';
import { QuarantineEntry, QuarantinePurgeResponse } from '../../types';
import { formatBytes } from '../../utils/format';

const { Text, Paragraph } = Typography;

interface Props {
  entry: QuarantineEntry | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isAdmin: boolean;
  allowMutation: boolean;
  allowDelete: boolean;
}

export const PurgeConfirmModal: React.FC<Props> = ({
  entry,
  open,
  onClose,
  onSuccess,
  isAdmin,
  allowMutation,
  allowDelete,
}) => {
  const queryClient = useQueryClient();
  const [confirmInput, setConfirmInput] = useState('');
  const [purgeResult, setPurgeResult] = useState<QuarantinePurgeResponse | null>(null);

  useEffect(() => {
    if (open) {
      setConfirmInput('');
      setPurgeResult(null);
    }
  }, [open, entry?.id]);

  const purgeMutation = useMutation({
    mutationFn: async () => {
      if (!entry) {
        throw new Error('隔离条目不存在');
      }
      if (!isAdmin || !allowMutation || !allowDelete) {
        throw new Error('当前系统安全配置或权限禁止执行永久清除操作');
      }
      if (confirmInput !== 'DELETE') {
        throw new Error('确认词不正确，必须严格输入大写的 DELETE');
      }
      return quarantineApi.purge(entry.id, { confirmation: confirmInput });
    },
    onSuccess: (result) => {
      setPurgeResult(result);
      message.success(`隔离文件 #${entry?.id} 已按普通文件删除（unlink）语义清除`);
      queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      onSuccess();
    },
    onError: (err: any) => {
      message.error(err.message || '清除隔离文件失败');
    },
  });

  if (!entry) return null;

  const isConfirmed = confirmInput === 'DELETE';
  const canPurge = isAdmin && allowMutation && allowDelete;
  const survivorPaths = purgeResult?.hardlink_survivor_paths || [];
  const independentCopyPaths = purgeResult?.independent_copy_paths || [];

  return (
    <Modal\n      className="nfc-overlay-modal"
      title={
        <Space>
          <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
          <span style={{ color: '#ff4d4f' }}>永久清除文件 #{entry.id}（普通文件删除）</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      onOk={() => (purgeResult ? onClose() : purgeMutation.mutate())}
      okText={purgeResult ? '关闭' : '永久清除 (unlink)'}
      cancelText="取消"
      confirmLoading={purgeMutation.isPending}
      okButtonProps={{
        danger: !purgeResult,
        disabled: purgeResult ? false : !canPurge || !isConfirmed || purgeMutation.isPending,
      }}
      destroyOnClose
      width={660}
    >
      {!isAdmin && (
        <Alert
          message="权限不足"
          description="只有系统管理员 (admin) 允许执行隔离文件的永久清除操作。"
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {!allowMutation && (
        <Alert
          message="只读安全模式生效中 (ALLOW_MUTATION=false)"
          description="系统当前处于只读保护模式，禁止执行任何永久清除操作。"
          type="warning"
          showIcon
          icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}

      {!allowDelete && (
        <Alert
          message="系统永久删除保护已开启 (ALLOW_DELETE=false)"
          description="服务端配置已禁用永久文件删除。需要由系统管理员明确开启 ALLOW_DELETE 后才能继续。"
          type="warning"
          showIcon
          icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}

      {!purgeResult && (
        <Alert
          message="不可逆的文件系统删除"
          description="此操作使用普通文件删除（unlink）语义，只删除 NFC 拥有并经过身份核验的隔离区路径；不会覆盖文件内容，也不会扩大到同 inode 的外部 hard link。若仍有其他 hard link，底层数据仍会被那些路径引用。"
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="原始路径">
          <Text code copyable style={{ wordBreak: 'break-all' }}>
            {entry.original_path}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label="隔离区路径">
          <Text code copyable style={{ wordBreak: 'break-all' }}>
            {entry.quarantine_path}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label="文件大小">
          <Text strong type="danger">
            {formatBytes(entry.size)}
          </Text>
        </Descriptions.Item>
      </Descriptions>

      {purgeResult ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="success"
            showIcon
            message={`隔离区路径已清除 · ${purgeResult.purge_semantics || 'unlink_v1'}`}
            description={`已移除 ${purgeResult.removed_count ?? 0} 个 NFC-owned pathname；survivor_scope=${purgeResult.survivor_scope || 'indexed_roots_only'}`}
          />

          {purgeResult.survivor_status === 'found' ? (
            <Alert
              type="warning"
              showIcon
              message="当前隔离副本已清除，但索引范围内仍发现存活 hard link"
              description={
                <List
                  size="small"
                  dataSource={survivorPaths}
                  renderItem={(path) => <List.Item><Text code>{path}</Text></List.Item>}
                />
              }
            />
          ) : purgeResult.survivor_status === 'incomplete' ? (
            <Alert
              type="warning"
              showIcon
              message="隔离区路径已清除，但索引范围内 hard link 核验不完整"
              description="advisory 查询不完整不会改变已经完成的 unlink 结果。"
            />
          ) : (
            <Alert
              type="info"
              showIcon
              message="索引范围内未发现存活 hard link"
              description={`检查状态：${purgeResult.survivor_status || 'none_found'}`}
            />
          )}

          {independentCopyPaths.length > 0 && (
            <Alert
              type="info"
              showIcon
              message="发现同内容但不同 inode 的独立副本"
              description={
                <List
                  size="small"
                  dataSource={independentCopyPaths}
                  renderItem={(path) => <List.Item><Text code>{path}</Text></List.Item>}
                />
              }
            />
          )}
        </Space>
      ) : (
        <div style={{ marginTop: 16, background: '#fff2f0', padding: 16, borderRadius: 8, border: '1px solid #ffccc7' }}>
          <Paragraph style={{ margin: 0, marginBottom: 8, fontWeight: 500, color: '#cf1322' }}>
            安全防呆核验：如确需永久删除，请在下方文本框中输入大写的 <Text code strong style={{ color: '#cf1322' }}>DELETE</Text>：
          </Paragraph>
          <Input
            placeholder="请输入 DELETE"
            value={confirmInput}
            onChange={(e) => setConfirmInput(e.target.value)}
            disabled={!canPurge || purgeMutation.isPending}
            status={confirmInput && !isConfirmed ? 'error' : undefined}
            prefix={<DeleteOutlined style={{ color: '#ff4d4f' }} />}
          />
          {confirmInput && !isConfirmed && (
            <Text type="danger" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
              必须严格输入全大写字母 &quot;DELETE&quot;
            </Text>
          )}
        </div>
      )}
    </Modal>
  );
};
