import React, { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import {
  getPlanDeleteAvailability, getPlanDeleteConfirmationContent,
  invalidatePlanDeleteFailure,
} from './plan_cleanup';

export interface PlanDeleteButtonProps {
  plan: {
    id: number;
    status: string;
    name?: string;
    active_work_job_id?: number | null;
    active_work_job_status?: string | null;
    active_work_job_recovered_after_restart?: boolean;
  };
  onDelete: () => void | Promise<unknown>;
  loading?: boolean;
  size?: 'small' | 'middle' | 'large';
  type?: 'link' | 'text' | 'default' | 'primary';
  danger?: boolean;
  buttonText?: string;
}

/** A readonly availability fence followed by a true explicit Radix confirmation. */
export const PlanDeleteButton: React.FC<PlanDeleteButtonProps> = ({
  plan, onDelete, loading = false, size = 'small',
  type = 'link', danger = true, buttonText = '删除',
}) => {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const singleFlight = useRef(false);
  const { canDelete, reason } = getPlanDeleteAvailability(plan);
  const { title, description } = getPlanDeleteConfirmationContent(plan);
  const busy = loading || submitting;
  const handleConfirm = async () => {
    if (!canDelete || busy || singleFlight.current) return;
    singleFlight.current = true;
    setSubmitting(true);
    try {
      await onDelete();
      setOpen(false);
    } catch {
      invalidatePlanDeleteFailure(queryClient, plan.id);
    } finally {
      singleFlight.current = false;
      setSubmitting(false);
    }
  };
  return (
    <>
      <span title={!canDelete ? reason : undefined}>
        <ConsoleButton
          size={size === 'small' ? 'sm' : 'md'}
          variant={!canDelete || !danger ? 'secondary' : 'danger'}
          className={type === 'link' || type === 'text' ? 'nfc-v2-plan-delete-subtle' : ''}
          leadingIcon={<ConsoleIcon name="trash" size={15} />}
          disabled={!canDelete || busy}
          loading={busy}
          onClick={() => { if (canDelete && !busy) setOpen(true); }}>
          {buttonText}
        </ConsoleButton>
      </span>
      <ConsoleConfirmDialog open={open}
        onOpenChange={next => { if (!busy) setOpen(next); }}
        title={title} description={description} danger
        confirmText="确认删除" disabled={!canDelete || busy}
        busy={busy} onConfirm={() => { void handleConfirm(); }} />
    </>
  );
};
