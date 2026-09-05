import React, { useState, useEffect } from 'react';
import {
  Modal,
  Input,
  Typography,
  Descriptions,
  Alert,
  message,
  Space,
} from 'antd';
import { DeleteOutlined, ExclamationCircleOutlined, LockOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quarantineApi } from '../../api/quarantine';
import { QuarantineEntry } from '../../types';
import { formatBytes } from '../../utils/format';

const { Text, Paragraph } = Typography;

interface Props {
  entry: QuarantineEntry | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isAdmin: boolean;
  allowDelete: boolean;
}

export const PurgeConfirmModal: React.FC<Props> = ({
  entry,
  open,
  onClose,
  onSuccess,
  isAdmin,
  allowDelete,
}) => {
  const queryClient = useQueryClient();
  const [confirmInput, setConfirmInput] = useState('');

  useEffect(() => {
    if (open) {
      setConfirmInput('');
    }
  }, [open]);

  const purgeMutation = useMutation({
    mutationFn: async () => {
      if (!entry) return;
      if (confirmInput !== 'DELETE') {
        throw new Error('确认词不正确，必须严格输入大写的 DELETE');
      }
      return quarantineApi.purge(entry.id, { confirmation: confirmInput });
    },
    onSuccess: () => {
      message.success(`隔离文件 #${entry?.id} 已被永久彻底清除`);
      queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      onSuccess();
      onClose();
    },
    onError: (err: any) => {
      message.error(err.message || '清除隔离文件失败');
    },
  });

  if (!entry) return null;

  const isConfirmed = confirmInput === 'DELETE';
  const canPurge = isAdmin && allowDelete;

  return (
    <Modal
      title={
        <Space>
          <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
          <span style={{ color: '#ff4d4f' }}>永久彻底清除文件 #{entry.id} (Purge)</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      onOk={() => purgeMutation.mutate()}
      okText="永久删除 (不可撤销)"
      cancelText="取消"
      confirmLoading={purgeMutation.isPending}
      okButtonProps={{
        danger: true,
        disabled: !canPurge || !isConfirmed || purgeMutation.isPending,
      }}
      destroyOnClose
      width={600}
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

      {!allowDelete && (
        <Alert
          message="系统永久删除保护已开启 (ALLOW_DELETE=false)"
          description="服务端配置已禁用永久文件删除。若需彻底清理磁盘，需由系统管理员修改 Docker Compose 环境变量并重启服务。"
          type="warning"
          showIcon
          icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}

      <Alert
        message="极度危险操作警告"
        description="此操作将彻底从磁盘上物理删除该隔离文件，且无法通过任何撤销计划或回收机制恢复！"
        type="error"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="原始路径">
          <Text code copyable style={{ wordBreak: 'break-all' }}>
            {entry.original_path}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label="隔离区物理路径">
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
    </Modal>
  );
};
