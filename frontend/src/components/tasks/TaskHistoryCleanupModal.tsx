import React, { useState } from 'react';
import { Button, Modal, Checkbox, Alert, Space, Typography, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import { TerminalTaskStatus } from '../../types/task';

const { Text } = Typography;

interface Props {
  onCleaned?: () => void;
}

const TERMINAL_OPTIONS: { label: string; value: TerminalTaskStatus }[] = [
  { label: '已完成 (completed)', value: 'completed' },
  { label: '已失败 (failed)', value: 'failed' },
  { label: '已取消 (cancelled)', value: 'cancelled' },
];

export const TaskHistoryCleanupModal: React.FC<Props> = ({ onCleaned }) => {
  const [open, setOpen] = useState(false);
  const [selectedStatuses, setSelectedStatuses] = useState<TerminalTaskStatus[]>([
    'completed',
    'failed',
    'cancelled',
  ]);
  const queryClient = useQueryClient();

  const handleOpen = () => {
    setSelectedStatuses(['completed', 'failed', 'cancelled']);
    setOpen(true);
  };

  const handleClose = () => {
    setOpen(false);
  };

  const cleanupMutation = useMutation({
    mutationFn: (statuses: TerminalTaskStatus[]) => tasksApi.clearTaskHistory(statuses),
    onSuccess: async (res) => {
      message.success(`已清理 ${res.deleted_count} 个历史任务`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tasksList'] }),
        queryClient.invalidateQueries({ queryKey: ['taskDetail'] }),
        queryClient.invalidateQueries({ queryKey: ['taskLogs'] }),
      ]);
      setOpen(false);
      onCleaned?.();
    },
    onError: (err: Error) => {
      message.error(err.message || '清理历史任务失败');
    },
  });

  const handleConfirm = () => {
    if (selectedStatuses.length === 0) {
      return;
    }
    cleanupMutation.mutate(selectedStatuses);
  };

  return (
    <>
      <Button danger icon={<DeleteOutlined />} onClick={handleOpen}>
        清理历史
      </Button>

      <Modal
        title="清理任务历史"
        open={open}
        onCancel={handleClose}
        footer={[
          <Button key="cancel" onClick={handleClose}>
            取消
          </Button>,
          <Button
            key="confirm"
            danger
            type="primary"
            disabled={selectedStatuses.length === 0}
            loading={cleanupMutation.isPending}
            onClick={handleConfirm}
          >
            确认清理
          </Button>,
        ]}
        destroyOnClose
      >
        <Space direction="vertical" size={16} style={{ width: '100%', marginTop: 8 }}>
          <Alert
            type="warning"
            showIcon
            message="清理范围说明"
            description="该操作会清理所有任务类型中符合所选终态的历史任务，不是仅清理当前分页或当前任务类型筛选结果。"
          />

          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              选择要清理的历史任务状态：
            </Text>
            <Checkbox.Group
              options={TERMINAL_OPTIONS}
              value={selectedStatuses}
              onChange={(checked) => setSelectedStatuses(checked as TerminalTaskStatus[])}
            />
          </div>

          <div
            style={{
              background: '#f8fafc',
              padding: '12px 16px',
              borderRadius: 8,
              border: '1px solid #e2e8f0',
              fontSize: 12,
              color: '#64748b',
            }}
          >
            <Text strong style={{ color: '#334155' }}>
              影响与安全说明：
            </Text>
            <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
              <li>选中的终态任务元数据及其关联事件日志（Task Logs）将被永久删除。</li>
              <li>
                <strong style={{ color: '#059669' }}>绝不会删除</strong> NAS 存储上的任何文件。
              </li>
              <li>
                <strong style={{ color: '#059669' }}>绝不会删除</strong> Audit 审计记录。
              </li>
              <li>排队中、执行中、暂停中或取消中的任务受系统保护，不会受到任何影响。</li>
            </ul>
          </div>
        </Space>
      </Modal>
    </>
  );
};
