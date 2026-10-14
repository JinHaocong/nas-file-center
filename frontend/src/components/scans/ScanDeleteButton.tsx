import React, { useRef, useState } from 'react';
import { getScanDeleteAvailability } from './scan_cleanup';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../ui/ConsoleIcon';

export interface ScanDeleteButtonProps {
  scan: { id: number; status: string; has_dependent_plan?: boolean };
  onDelete: () => void | Promise<unknown>;
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
  const [submitting, setSubmitting] = useState(false);
  const deleteInFlight = useRef(false);
  const { canDelete, reason } = getScanDeleteAvailability(scan);
  const busy = loading || submitting;
  const unavailable = !canDelete || busy;

  const confirmDelete = async () => {
    // Recheck linked plans/status before taking the synchronous event lock.
    if (!getScanDeleteAvailability(scan).canDelete || busy || deleteInFlight.current) return;
    deleteInFlight.current = true;
    setSubmitting(true);
    try {
      await onDelete();
      setOpen(false);
    } catch {
      // The parent mutation handles the error notice; a failed delete can be retried.
    } finally {
      deleteInFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <>
      <span title={!canDelete ? reason || undefined : undefined}>
        <ConsoleButton
          variant={type === 'text' || type === 'link' ? 'ghost' : danger ? 'danger' : 'secondary'}
          size={size === 'small' ? 'sm' : 'md'}
          leadingIcon={<ConsoleIcon name="archive" size={15} />}
          disabled={unavailable}
          loading={busy}
          aria-label={'删除扫描 #' + scan.id}
          onClick={() => { if (!unavailable && !deleteInFlight.current) setOpen(true); }}
        >{buttonText}</ConsoleButton>
      </span>
      <ConsoleConfirmDialog
        open={open}
        onOpenChange={next => { if (!busy && !deleteInFlight.current) setOpen(next); }}
        title={'确认删除扫描 #' + scan.id + '？'}
        description={<p>将永久删除扫描元数据和发现的重复组信息，该操作不可逆。关联执行计划的扫描记录不可删除。本操作不会直接删除 NAS 上的文件。</p>}
        confirmText="确认删除"
        onConfirm={() => { void confirmDelete(); }}
        busy={busy}
        disabled={!canDelete || busy}
        danger
      />
    </>
  );
};
