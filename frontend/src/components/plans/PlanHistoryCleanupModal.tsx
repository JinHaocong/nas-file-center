import React, { useState } from 'react';
import { Button, Modal, Checkbox, Alert, Space, Typography, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import { PlanHistoryStatus } from '../../types';

const { Text } = Typography;

interface Props {
  onCleaned?: () => void;
}

const PLAN_HISTORY_OPTIONS: { label: string; value: PlanHistoryStatus }[] = [
  { label: '已完成 (completed)', value: 'completed' },
  { label: '已失败 (failed)', value: 'failed' },
];

export const PlanHistoryCleanupModal: React.FC<Props> = ({ onCleaned }) => {
  const [open, setOpen] = useState(false);
  const [selectedStatuses, setSelectedStatuses] = useState<PlanHistoryStatus[]>([
    'completed',
    'failed',
  ]);
  const queryClient = useQueryClient();

  const handleOpen = () => {
    setSelectedStatuses(['completed', 'failed']);
    setOpen(true);
  };

  const handleClose = () => {
    setOpen(false);
  };

  const cleanupMutation = useMutation({
    mutationFn: (statuses: PlanHistoryStatus[]) => plansApi.clearHistory(statuses),
    onSuccess: async (res) => {
      message.success(`已清理 ${res.deleted_count} 个计划历史记录`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['plansList'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] }),
        queryClient.invalidateQueries({ queryKey: ['scansList'] }),
      ]);
      setOpen(false);
      onCleaned?.();
    },
    onError: (err: any) => {
      message.error(err.message || '清理计划历史失败');
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
      <Button icon={<DeleteOutlined />} onClick={handleOpen}>
        清理计划历史
      </Button>

      <Modal
      className="nfc-overlay-modal nfc-history-cleanup-modal nfc-plan-history-cleanup-modal"
        title="清理计划历史"
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
        <Space className="nfc-history-cleanup-stack" direction="vertical" size={16}>
          <Alert
            type="warning"
            showIcon
            message="批量清理说明"
            description="批量清理仅删除选定状态的已终态计划历史元数据与条目记录（BatchPlan 及 BatchPlanItem），不会撤销已执行的文件操作（Delete ≠ Undo）。"
          />

          <div>
            <Text strong className="nfc-history-cleanup-label">
              选择要清理的历史计划状态：
            </Text>
            <Checkbox.Group
              options={PLAN_HISTORY_OPTIONS}
              value={selectedStatuses}
              onChange={(checked) => setSelectedStatuses(checked as PlanHistoryStatus[])}
            />
          </div>

          <div className="nfc-history-cleanup-note">
            <Text strong className="nfc-history-cleanup-note-title">
              影响与安全说明：
            </Text>
            <ul className="nfc-history-cleanup-list">
              <li>选中的终态计划元数据及操作条目将被永久删除。</li>
              <li>
                <strong className="nfc-success-text">绝不会删除或修改</strong> NAS 存储上的任何文件。
              </li>
              <li>
                <strong className="nfc-success-text">绝不会删除</strong> Audit 审计记录与关联的任务。
              </li>
              <li>草稿 (draft)、已冻结 (frozen)、已就绪 (ready) 及运行中 (validating / executing) 的计划受系统保护，不受影响。</li>
            </ul>
          </div>
        </Space>
      </Modal>
    </>
  );
};
