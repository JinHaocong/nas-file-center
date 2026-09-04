import React from 'react';
import { Button, Popconfirm, Tooltip } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  getPlanDeleteAvailability,
  getPlanDeleteConfirmationContent,
  invalidatePlanDeleteFailure,
} from './plan_cleanup';

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
  const queryClient = useQueryClient();
  const { canDelete, reason } = getPlanDeleteAvailability(plan);
  const { title: popconfirmTitle, description: popconfirmDescription } =
    getPlanDeleteConfirmationContent(plan);

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

  const handleConfirm = async () => {
    try {
      await onDelete();
    } catch (err: any) {
      invalidatePlanDeleteFailure(queryClient, plan.id);
    }
  };

  return (
    <Popconfirm
      title={popconfirmTitle}
      description={popconfirmDescription}
      okText="确认删除"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      onConfirm={handleConfirm}
    >
      {btn}
    </Popconfirm>
  );
};
