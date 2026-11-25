import React, { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import type { TerminalTaskStatus } from '../../types/task';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleCheckbox } from '../ui/ConsoleCheckbox';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';
import { formatReportCleanupFeedback } from './task_cleanup';

interface Props { onCleaned?: () => void; }

const TERMINAL_OPTIONS: { label: string; value: TerminalTaskStatus }[] = [
  { label: '已完成 (completed)', value: 'completed' },
  { label: '已失败 (failed)', value: 'failed' },
  { label: '已取消 (cancelled)', value: 'cancelled' },
];

export const TaskHistoryCleanupModal: React.FC<Props> = ({ onCleaned }) => {
  const [open, setOpen] = useState(false);
  const [selectedStatuses, setSelectedStatuses] = useState<TerminalTaskStatus[]>([
    'completed', 'failed', 'cancelled',
  ]);
  // Synchronous guard closes the gap before React Query commits isPending.
  const submitting = useRef(false);
  // Controlled Radix Dialog has no Dialog.Trigger; save the actual launcher before autofocus.
  const returnFocusTarget = useRef<HTMLElement | null>(null);
  const queryClient = useQueryClient();
  const toast = useConsoleToast();

  const handleOpen = () => {
    if (submitting.current) return;
    setSelectedStatuses(['completed', 'failed', 'cancelled']);
    setOpen(true);
  };

  const cleanupMutation = useMutation({
    mutationFn: (statuses: TerminalTaskStatus[]) => tasksApi.clearTaskHistory(statuses),
    onSuccess: async res => {
      const message = `已清理 ${res.deleted_count} 个历史任务`;
      const feedback = formatReportCleanupFeedback(res.report_cleanup);
      toast.success(feedback ? `${message}，${feedback}` : message);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tasksList'] }),
        queryClient.invalidateQueries({ queryKey: ['recentTasks'] }),
        queryClient.invalidateQueries({ queryKey: ['taskDetail'] }),
        queryClient.invalidateQueries({ queryKey: ['taskLogs'] }),
        queryClient.invalidateQueries({ queryKey: ['organizerReports'] }),
      ]);
      setOpen(false);
      onCleaned?.();
    },
    onError: (err: Error) => {
      toast.error(err.message || '清理历史任务失败');
    },
  });

  const toggle = (status: TerminalTaskStatus, checked: boolean) => {
    if (submitting.current || cleanupMutation.isPending) return;
    setSelectedStatuses(previous => checked
      ? [...previous.filter(item => item !== status), status]
      : previous.filter(item => item !== status));
  };

  const closeSafely = () => {
    if (!submitting.current && !cleanupMutation.isPending) setOpen(false);
  };
  const handleConfirm = async () => {
    if (submitting.current || cleanupMutation.isPending || selectedStatuses.length === 0) return;
    // A stable snapshot, restricted to terminal statuses, prevents async selection drift.
    const selected = TERMINAL_OPTIONS.map(option => option.value)
      .filter(status => selectedStatuses.includes(status));
    if (selected.length === 0) return;
    submitting.current = true;
    try {
      await cleanupMutation.mutateAsync(selected);
    } catch {
      // onError already reports errors; keep the dialog open to allow explicit retry.
    } finally {
      submitting.current = false;
    }
  };

  return (
    <>
      <ConsoleButton variant="danger"
        leadingIcon={<ConsoleIcon name="archive" size={16} />} onClick={handleOpen}>
        清理历史
      </ConsoleButton>
      <Dialog.Root open={open} onOpenChange={next => {
        if (!cleanupMutation.isPending && !submitting.current) setOpen(next);
      }}>
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay" />
          <Dialog.Content
            className="nfc-v2-dialog nfc-v2-history-dialog nfc-overlay-modal nfc-history-cleanup-modal nfc-task-history-cleanup-modal"
            onOpenAutoFocus={() => {
              const active = document.activeElement;
              returnFocusTarget.current = active instanceof HTMLElement && active !== document.body
                ? active : null;
            }}
            onCloseAutoFocus={event => {
              const target = returnFocusTarget.current;
              returnFocusTarget.current = null;
              // The task ledger can refresh/remove or disable the launcher.
              // Only restore a still-connected, enabled target; otherwise keep Radix fallback.
              if (target?.isConnected && !target.matches(':disabled')) {
                event.preventDefault();
                target.focus();
              }
            }}
            onEscapeKeyDown={event => { if (cleanupMutation.isPending || submitting.current) event.preventDefault(); }}
            onPointerDownOutside={event => event.preventDefault()}
          >
            <header className="nfc-v2-dialog-heading">
              <span className="nfc-v2-dialog-icon is-danger">
                <ConsoleIcon name="shield-check" size={20} />
              </span>
              <div>
                <Dialog.Title>清理任务历史</Dialog.Title>
                <Dialog.Description>清理选中终态的任务记录和可安全回收的智能整理报告。</Dialog.Description>
              </div>
              <button type="button" className="nfc-v2-dialog-close"
                disabled={cleanupMutation.isPending} aria-label="关闭历史清理窗口"
                onClick={closeSafely}><ConsoleIcon name="x" size={18} /></button>
            </header>

            <div className="nfc-v2-history-body nfc-history-cleanup-stack">
              <div className="nfc-v2-history-warning" role="note">
                <ConsoleIcon name="shield-check" size={18} />
                <div><strong>清理范围说明</strong>
                  <p>清理适用于所有符合所选终态的任务，包括其他分页和任务类型。</p>
                </div>
              </div>

              <fieldset className="nfc-v2-history-statuses">
                <legend>选择要清理的历史任务状态：</legend>
                {TERMINAL_OPTIONS.map(option => (
                  <label key={option.value}>
                    <ConsoleCheckbox value={option.value}
                      checked={selectedStatuses.includes(option.value)}
                      disabled={cleanupMutation.isPending}
                      onCheckedChange={checked => toggle(option.value, checked)} />
                    <span>{option.label}</span>
                  </label>
                ))}
              </fieldset>

              <section className="nfc-v2-history-impacts" aria-label="影响与安全说明">
                <strong>清理影响</strong>
                <ul className="nfc-history-cleanup-list">
                  <li>可安全回收的智能整理报告会排队清理。</li>
                  <li>恢复所需资料和关联事件日志（Task Logs）会保留。</li>
                  <li>NAS 媒体文件、Audit 审计记录和活动任务会保留。</li>
                </ul>
              </section>
            </div>

            <footer className="nfc-v2-confirm-actions">
              <ConsoleButton disabled={cleanupMutation.isPending}
                onClick={closeSafely}>取消</ConsoleButton>
              <ConsoleButton variant="danger"
                disabled={selectedStatuses.length === 0 || cleanupMutation.isPending}
                loading={cleanupMutation.isPending} onClick={() => { void handleConfirm(); }}>
                确认清理
              </ConsoleButton>
            </footer>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
};
