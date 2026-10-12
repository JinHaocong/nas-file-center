import React, { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import type { PlanHistoryStatus } from '../../types';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';

interface Props { onCleaned?: () => void; }

const PLAN_HISTORY_OPTIONS: { label: string; value: PlanHistoryStatus }[] = [
  { label: '已完成 (completed)', value: 'completed' },
  { label: '已失败 (failed)', value: 'failed' },
];

/** Metadata cleanup only: terminal statuses selected explicitly, never an Undo. */
export const PlanHistoryCleanupModal: React.FC<Props> = ({ onCleaned }) => {
  const [open, setOpen] = useState(false);
  const [selectedStatuses, setSelectedStatuses] = useState<PlanHistoryStatus[]>(['completed', 'failed']);
  const submitting = useRef(false);
  const queryClient = useQueryClient();
  const toast = useConsoleToast();

  const cleanupMutation = useMutation({
    mutationFn: (statuses: PlanHistoryStatus[]) => plansApi.clearHistory(statuses),
    onSuccess: async res => {
      toast.success('已清理 ' + res.deleted_count + ' 个计划历史记录');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['plansList'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] }),
        queryClient.invalidateQueries({ queryKey: ['scansList'] }),
      ]);
      setOpen(false);
      onCleaned?.();
    },
    onError: (error: unknown) => {
      toast.error(getStructuredApiError(error).message || '清理计划历史失败');
    },
  });

  const handleOpen = () => {
    if (submitting.current) return;
    setSelectedStatuses(['completed', 'failed']);
    setOpen(true);
  };
  const handleConfirm = async () => {
    if (submitting.current || selectedStatuses.length === 0) return;
    submitting.current = true;
    try {
      // Deliberately immutable snapshot of only the two allowed terminal statuses.
      const selected = PLAN_HISTORY_OPTIONS.map(x => x.value)
        .filter(x => selectedStatuses.includes(x));
      if (selected.length === 0) return;
      await cleanupMutation.mutateAsync(selected);
    } catch {
      // Error already reported by mutation.onError; allow explicit retry.
    } finally {
      submitting.current = false;
    }
  };

  return (
    <>
      <ConsoleButton leadingIcon={<ConsoleIcon name="trash" size={16} />}
        onClick={handleOpen}>清理计划历史</ConsoleButton>
      <Dialog.Root open={open} onOpenChange={next => {
        if (!cleanupMutation.isPending && !submitting.current) setOpen(next);
      }}>
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
          <Dialog.Content className="nfc-v2-dialog nfc-overlay-modal nfc-history-cleanup-modal nfc-plan-history-cleanup-modal nfc-v2-plan-history-dialog"
            onEscapeKeyDown={event => { if (cleanupMutation.isPending || submitting.current) event.preventDefault(); }}
            onPointerDownOutside={event => event.preventDefault()}>
            <header className="nfc-v2-dialog-heading">
              <span className="nfc-v2-dialog-icon is-danger"><ConsoleIcon name="trash" size={20} /></span>
              <div><Dialog.Title>清理计划历史</Dialog.Title></div>
              <button type="button" className="nfc-v2-dialog-close" aria-label="关闭清理窗口"
                disabled={cleanupMutation.isPending}
                onClick={() => setOpen(false)}><ConsoleIcon name="x" size={18} /></button>
            </header>
            <Dialog.Description asChild>
              <div className="nfc-history-cleanup-stack nfc-v2-plan-history-body">
                <div className="nfc-v2-plan-cleanup-warning" role="note">
                  <ConsoleIcon name="info" size={18} />
                  <div><strong>批量清理说明</strong>
                    <p>批量清理仅删除选定状态的已终态计划历史元数据与条目记录（BatchPlan 及 BatchPlanItem），不会撤销已执行的文件操作（Delete ≠ Undo）。</p>
                  </div>
                </div>
                <fieldset className="nfc-v2-plan-history-options">
                  <legend className="nfc-history-cleanup-label">选择要清理的历史计划状态：</legend>
                  {PLAN_HISTORY_OPTIONS.map(item => (
                    <label key={item.value}>
                      <input type="checkbox" checked={selectedStatuses.includes(item.value)}
                        disabled={cleanupMutation.isPending}
                        onChange={event => {
                          const next = event.target.checked
                            ? [...selectedStatuses, item.value]
                            : selectedStatuses.filter(value => value !== item.value);
                          setSelectedStatuses(next);
                        }} />
                      <span>{item.label}</span>
                    </label>
                  ))}
                </fieldset>
                <div className="nfc-history-cleanup-note">
                  <strong className="nfc-history-cleanup-note-title">影响与安全说明：</strong>
                  <ul className="nfc-history-cleanup-list">
                    <li>选中的终态计划元数据及操作条目将被永久删除。</li>
                    <li><strong className="nfc-success-text">绝不会删除或修改</strong> NAS 存储上的任何文件。</li>
                    <li><strong className="nfc-success-text">绝不会删除</strong> Audit 审计记录与关联的任务。</li>
                    <li>草稿 (draft)、已冻结 (frozen)、已就绪 (ready) 及运行中 (validating / executing) 的计划受系统保护，不受影响。</li>
                  </ul>
                </div>
              </div>
            </Dialog.Description>
            <div className="nfc-v2-confirm-actions">
              <ConsoleButton disabled={cleanupMutation.isPending}
                onClick={() => setOpen(false)}>取消</ConsoleButton>
              <ConsoleButton variant="danger" loading={cleanupMutation.isPending}
                disabled={selectedStatuses.length === 0}
                onClick={() => { void handleConfirm(); }}>确认清理</ConsoleButton>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
};
