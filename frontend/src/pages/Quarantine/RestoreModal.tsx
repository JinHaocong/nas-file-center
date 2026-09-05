import React, { useState, useEffect } from 'react';
import {
  Modal,
  Form,
  Radio,
  Input,
  Typography,
  Descriptions,
  Alert,
  message,
  Space,
  Tooltip,
} from 'antd';
import { UndoOutlined, LockOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quarantineApi } from '../../api/quarantine';
import { QuarantineEntry, QuarantineConflictPolicy } from '../../types';
import { formatBytes } from '../../utils/format';

const { Text } = Typography;

interface Props {
  entry: QuarantineEntry | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isSafeMode?: boolean;
}

export const RestoreModal: React.FC<Props> = ({
  entry,
  open,
  onClose,
  onSuccess,
  isSafeMode = false,
}) => {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const [conflictPolicy, setConflictPolicy] = useState<QuarantineConflictPolicy>('skip');

  useEffect(() => {
    if (open) {
      setConflictPolicy('skip');
      form.resetFields();
      form.setFieldsValue({
        conflict_policy: 'skip',
        custom_target: '',
      });
    }
  }, [open, form]);

  const restoreMutation = useMutation({
    mutationFn: async (values: { conflict_policy: QuarantineConflictPolicy; custom_target?: string }) => {
      if (!entry) return;
      return quarantineApi.restore(entry.id, {
        conflict_policy: values.conflict_policy,
        custom_target: values.conflict_policy === 'manual' ? values.custom_target?.trim() : undefined,
      });
    },
    onSuccess: (res) => {
      if (!res) return;
      if (res.state === 'skipped') {
        message.warning(res.reason || '目标文件已存在，恢复操作已安全跳过');
      } else if (res.conflict_resolved) {
        message.success(`恢复成功！因原目标路径已存在，已自动重命名保存至: ${res.restored_to_path}`);
      } else {
        message.success(`已成功将文件恢复至: ${res.restored_to_path}`);
      }
      queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      onSuccess();
      onClose();
    },
    onError: (err: any) => {
      message.error(err.message || '恢复文件失败');
    },
  });

  const handleConfirm = async () => {
    try {
      const values = await form.validateFields();
      restoreMutation.mutate(values);
    } catch {
      // Form validation failed
    }
  };

  if (!entry) return null;

  return (
    <Modal
      title={
        <Space>
          <UndoOutlined style={{ color: '#1677ff' }} />
          <span>恢复隔离文件 #{entry.id}</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okText="确认恢复"
      cancelText="取消"
      confirmLoading={restoreMutation.isPending}
      okButtonProps={{
        disabled: isSafeMode || restoreMutation.isPending,
      }}
      destroyOnClose
      width={640}
    >
      {isSafeMode && (
        <Alert
          message="只读安全保护模式生效中"
          description="系统当前以 ALLOW_MUTATION=false 运行，禁止执行文件恢复与磁盘写入。如需恢复文件，请在服务端环境变量中开启写入权限。"
          type="warning"
          showIcon
          icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}

      <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="原始文件路径">
          <Text code copyable style={{ wordBreak: 'break-all' }}>
            {entry.original_path}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label="当前隔离路径">
          <Text code copyable style={{ wordBreak: 'break-all' }}>
            {entry.quarantine_path}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label="文件大小">
          <Text strong>{formatBytes(entry.size)}</Text>
        </Descriptions.Item>
        {entry.hash && (
          <Descriptions.Item label="内容 SHA256">
            <Text code copyable style={{ fontSize: 12 }}>
              {entry.hash}
            </Text>
          </Descriptions.Item>
        )}
      </Descriptions>

      <Form form={form} layout="vertical" initialValues={{ conflict_policy: 'skip' }}>
        <Form.Item
          name="conflict_policy"
          label={
            <Space>
              <Text strong>目标路径冲突处理策略</Text>
              <Tooltip title="当原路径已存在其他文件或目录时系统的处理方式。系统严禁直接覆盖目标文件。">
                <ExclamationCircleOutlined style={{ color: '#8c8c8c' }} />
              </Tooltip>
            </Space>
          }
          rules={[{ required: true, message: '请选择冲突策略' }]}
        >
          <Radio.Group
            onChange={(e) => setConflictPolicy(e.target.value)}
            disabled={isSafeMode || restoreMutation.isPending}
          >
            <Space direction="vertical" align="start">
              <Radio value="skip">
                <span>
                  <strong>跳过 (Skip - 默认)</strong>：若目标路径已存在同名实体，取消本次恢复，保持隔离状态不变。
                </span>
              </Radio>
              <Radio value="rename">
                <span>
                  <strong>自动重命名 (Rename)</strong>：若目标路径已被占用，自动保存为 <Text code>.restored-{entry.id}</Text> 避免覆盖。
                </span>
              </Radio>
              <Radio value="manual">
                <span>
                  <strong>指定目标路径 (Manual)</strong>：手动指定恢复目标绝对路径（必须在允许白名单目录内）。
                </span>
              </Radio>
            </Space>
          </Radio.Group>
        </Form.Item>

        {conflictPolicy === 'manual' && (
          <Form.Item
            name="custom_target"
            label="自定义恢复绝对路径"
            rules={[
              { required: true, message: '请输入自定义恢复目标路径' },
              {
                validator: (_, val) => {
                  if (val && !val.trim().startsWith('/')) {
                    return Promise.reject(new Error('路径必须为以 / 开头的绝对路径'));
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <Input
              placeholder="例如: /data/restored_files/my_file.txt"
              disabled={isSafeMode || restoreMutation.isPending}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
};
