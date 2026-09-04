import React from 'react';
import { Button, Popconfirm, Tooltip } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { getScanDeleteAvailability } from './scan_cleanup';

export interface ScanDeleteButtonProps {
  scan: {
    id: number;
    status: string;
    has_dependent_plan?: boolean;
  };
  onDelete: () => void | Promise<void>;
  loading?: boolean;
  size?: 'small' | 'middle' | 'large';
  type?: 'link' | 'text' | 'default' | 'primary';
  danger?: boolean;
  buttonText?: string;
}

export const ScanDeleteButton: React.FC<ScanDeleteButtonProps> = ({
  scan,
  onDelete,
  loading = false,
  size = 'small',
  type = 'link',
  danger = true,
  buttonText = '删除',
}) => {
  const { canDelete, reason } = getScanDeleteAvailability(scan);

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

  return (
    <Popconfirm
      title="确认删除此扫描记录？"
      description="将永久删除扫描元数据和发现的重复组信息，该操作不可逆。"
      okText="确认删除"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      onConfirm={onDelete}
    >
      {btn}
    </Popconfirm>
  );
};
