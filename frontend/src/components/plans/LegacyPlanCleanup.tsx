import React, { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../ui/ConsoleToast';
import {
  formatLegacyClearSuccessMessage,
  formatLegacyAlertDescription,
  LEGACY_CLEANUP_CONFIRM_DESCRIPTION,
} from './plan_cleanup';

export const LegacyPlanCleanup: React.FC = () => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const [open, setOpen] = useState(false);
  const inFlight = useRef(false);
  const { data: summary } = useQuery({
    queryKey: ['legacyPlanSummary'],
    queryFn: plansApi.getLegacySummary,
  });
  const clearLegacyMutation = useMutation({
    mutationFn: plansApi.clearLegacyPlans,
    onSuccess: async res => {
      toast.success(formatLegacyClearSuccessMessage(res.deleted_count, res.affected_scan_count));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['legacyPlanSummary'] }),
        queryClient.invalidateQueries({ queryKey: ['scansList'] }),
        queryClient.invalidateQueries({ queryKey: ['plansList'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] }),
      ]);
    },
    onError: (error: unknown) => {
      toast.error(getStructuredApiError(error).message || '清理旧版兼容计划失败');
    },
  });
  const handleConfirm = async () => {
    if (!summary?.plan_count || inFlight.current) return;
    inFlight.current = true;
    try {
      await clearLegacyMutation.mutateAsync();
      setOpen(false);
    } catch {
      // Error is surfaced by onError; confirmation remains open for retry.
    } finally {
      inFlight.current = false;
    }
  };
  if (!summary || summary.plan_count === 0) return null;
  return (
    <>
      <div className="nfc-legacy-plan-cleanup nfc-v2-legacy-plan-cleanup" role="note">
        <ConsoleIcon name="info" size={19} />
        <div className="nfc-v2-legacy-plan-main">
          <div className="nfc-legacy-plan-cleanup-heading">
            <strong>检测到旧版计划记录 ({summary.plan_count} 个)</strong>
            <ConsoleButton variant="danger" size="sm"
              disabled={clearLegacyMutation.isPending}
              loading={clearLegacyMutation.isPending}
              leadingIcon={<ConsoleIcon name="trash" size={15} />}
              onClick={() => setOpen(true)}>
              一键清理旧版计划
            </ConsoleButton>
          </div>
          <p className="nfc-legacy-plan-cleanup-description">
            {formatLegacyAlertDescription(summary)}
          </p>
        </div>
      </div>
      <ConsoleConfirmDialog open={open}
        onOpenChange={next => { if (!clearLegacyMutation.isPending) setOpen(next); }}
        title="确认清理旧版计划记录？"
        description={LEGACY_CLEANUP_CONFIRM_DESCRIPTION}
        confirmText="确认清理" danger
        busy={clearLegacyMutation.isPending}
        onConfirm={() => { void handleConfirm(); }} />
    </>
  );
};
