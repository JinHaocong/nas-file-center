import React, { useState } from 'react';
import { getScanDeleteAvailability } from './scan_cleanup';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../ui/ConsoleIcon';

export interface ScanDeleteButtonProps {
  scan: { id: number; status: string; has_dependent_plan?: boolean };
  onDelete: () => void | Promise<void>;
  loading?: boolean;
  size?: 'small' | 'middle' | 'large';
  type?: 'link' | 'text' | 'default' | 'primary';
  danger?: boolean;
  buttonText?: string;
}

export const ScanDeleteButton: React.FC<ScanDeleteButtonProps> = ({
  scan, onDelete, loading = false, size = 'small',
  type = 'link', danger = true, buttonText = '删除',
}) => {
  const [open, setOpen] = useState(false);
  const { canDelete, reason } = getScanDeleteAvailability(scan);
  const unavailable = !canDelete || loading;

  const confirmDelete = () => {
    // Re-evaluate on confirmation: a changed status or linked plan blocks deletion.
    if (!getScanDeleteAvailability(scan).canDelete || loading) return;
    onDelete();
  };

  return (
    <>
      <span title={!canDelete ? reason || undefined : undefined}>
        <ConsoleButton
          variant={type === 'text' || type === 'link' ? 'ghost' : danger ? 'danger' : 'secondary'}
          size={size === 'small' ? 'sm' : 'md'}
          leadingIcon={<ConsoleIcon name="archive" size={15} />}
          disabled={unavailable}
          loading={loading}
          aria-label={'删除扫描 #' + scan.id}
          onClick={() => { if (!unavailable) setOpen(true); }}
        >{buttonText}</ConsoleButton>
      </span>
      <ConsoleConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={'确认删除扫描 #' + scan.id + '？'}
        description={<p>将永久删除扫描元数据和发现的重复组信息，该操作不可逆。关联执行计划的扫描记录不可删除。本操作不会直接删除 NAS 上的文件。</p>}
        confirmText="确认删除"
        onConfirm={confirmDelete}
        busy={loading}
        disabled={!canDelete}
        danger
      />
    </>
  );
};
