import React from 'react';
import { Button, Popconfirm, Tooltip } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { getPlanDeleteAvailability } from './plan_cleanup';

export interface PlanDeleteButtonProps {
  plan: {
    id: number;
    status: string;
    name?: string;
  };
  onDelete: () => void | Promise<void>;
  loading?: boolean;
  size?: 'small' | 'middle' | 'large';
  type?: 'link' | 'text' | 'default' | 'primary';
  danger?: boolean;
  buttonText?: string;
}

export const PlanDeleteButton: React.FC<PlanDeleteButtonProps> = ({
  plan,
  onDelete,
  loading = false,
  size = 'small',
  type = 'link',
  danger = true,
  buttonText = '删除',
}) => {
  const { canDelete, reason, hasExecutionHistory } = getPlanDeleteAvailability(plan);

  const btn = (
    <Button
      size={size}
      type={type}
      danger={danger && canDelete}
      disabled={!canDelete || loading}
      loading={loading}
      icon={<DeleteOutlined />}
    >
      {buttonText}
    </Button>
  );

  if (!canDelete && reason) {
    return (
      <Tooltip title={reason}>
        <span>{btn}</span>
      </Tooltip>
    );
  }

  const description = hasExecutionHistory
    ? '该计划包含历史执行状态。删除仅清理计划记录与审计流水，不会撤销 NAS 文件操作（Delete ≠ Undo）。'
    : '删除未执行的计划记录，该操作不可逆。';

  return (
    <Popconfirm
      title="确认删除此执行计划？"
      description={description}
      okText="确认删除"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      onConfirm={onDelete}
    >
      {btn}
    </Popconfirm>
  );
};
