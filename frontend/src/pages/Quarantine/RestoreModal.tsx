import React, { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quarantineApi } from '../../api/quarantine';
import { getStructuredApiError } from '../../api/errors';
import type { QuarantineEntry, QuarantineConflictPolicy } from '../../types';
import { getQuarantineRestoreAvailability } from '../../components/quarantine/quarantine_rules';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { formatBytes } from '../../utils/format';

interface Props {
  entry: QuarantineEntry | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isSafeMode?: boolean;
}

/** One-file restore remains server-authoritative and never overwrites an existing target. */
export const RestoreModal: React.FC<Props> = ({
  entry, open, onClose, onSuccess, isSafeMode = false,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const inFlight = useRef(false);
  const [conflictPolicy, setConflictPolicy] = useState<QuarantineConflictPolicy>('skip');
  const [customTarget, setCustomTarget] = useState('');

  useEffect(() => {
    if (open && !inFlight.current) {
      setConflictPolicy('skip');
      setCustomTarget('');
    }
  }, [open, entry?.id]);

  const restoreMutation = useMutation({
    mutationFn: (payload: { conflict_policy: QuarantineConflictPolicy; custom_target?: string }) => {
      if (!entry) throw new Error('隔离条目不存在');
      if (isSafeMode) throw new Error('只读安全模式生效中，禁止执行恢复操作');
      const allowed = getQuarantineRestoreAvailability(isSafeMode, payload.conflict_policy, payload.custom_target);
      if (!allowed.canRestore) throw new Error(allowed.reason || '恢复请求无效');
      return quarantineApi.restore(entry.id, payload);
    },
    onSuccess: res => {
      if (res.state === 'skipped') {
        toast.info(res.reason || '目标文件已存在，恢复操作已安全跳过');
      } else if (res.conflict_resolved) {
        toast.success('恢复成功！因原目标路径已存在，已自动重命名保存至: ' + res.restored_to_path);
      } else {
        toast.success('已成功将文件恢复至: ' + res.restored_to_path);
      }
      void queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      onSuccess();
      onClose();
    },
    onError: (error: unknown) =>
      toast.error(getStructuredApiError(error).message || '恢复文件失败'),
  });

  const busy = restoreMutation.isPending;
  const availability = getQuarantineRestoreAvailability(isSafeMode, conflictPolicy, customTarget);
  const closeSafely = () => { if (!inFlight.current && !busy) onClose(); };
  const handleConfirm = async () => {
    if (!entry || !open || inFlight.current || busy) return;
    const checked = getQuarantineRestoreAvailability(isSafeMode, conflictPolicy, customTarget);
    if (!checked.canRestore) {
      toast.error(checked.reason || '无法恢复隔离文件');
      return;
    }
    // Snapshot the exact policy and trimmed target; no implicit overwrite or fallback.
    const payload = {
      conflict_policy: conflictPolicy,
      custom_target: conflictPolicy === 'manual' ? customTarget.trim() : undefined,
    };
    inFlight.current = true;
    try { await restoreMutation.mutateAsync(payload); }
    catch { /* Mutation error displayed by onError; retain the dialog for retry. */ }
    finally { inFlight.current = false; }
  };

  if (!entry) return null;
  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) closeSafely(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
        <Dialog.Content
          className="nfc-v2-dialog nfc-overlay-modal nfc-quarantine-restore-modal nfc-v2-quarantine-dialog"
          onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon"><ConsoleIcon name="archive" size={20} /></span>
            <div>
              <Dialog.Title>恢复隔离文件 #{entry.id}</Dialog.Title>
              <Dialog.Description className="nfc-v2-quarantine-subtitle">
                恢复前请检查目标路径和冲突处理策略。严禁覆盖已有文件。
              </Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dialog-close" aria-label="关闭恢复窗口"
              disabled={busy} onClick={closeSafely}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>
          <div className="nfc-v2-quarantine-body">
            {isSafeMode && <div className="nfc-v2-quarantine-alert is-warning" role="alert">
              <ConsoleIcon name="lock" size={18} />
              <div><strong>只读安全保护模式生效中</strong>
                <p>系统当前以 ALLOW_MUTATION=false 运行，禁止执行文件恢复与磁盘写入。如需恢复文件，请在服务端环境变量中开启写入权限。</p>
              </div>
            </div>}
            <dl className="nfc-v2-quarantine-facts nfc-quarantine-descriptions">
              <div><dt>原始文件路径</dt><dd><code className="nfc-breakall">{entry.original_path}</code></dd></div>
              <div><dt>当前隔离路径</dt><dd><code className="nfc-breakall">{entry.quarantine_path}</code></dd></div>
              <div><dt>文件大小</dt><dd>{formatBytes(entry.size)}</dd></div>
              {entry.hash && <div><dt>内容 SHA256</dt><dd><code className="nfc-mono-break">{entry.hash}</code></dd></div>}
            </dl>
            <fieldset className="nfc-v2-quarantine-options nfc-quarantine-restore-form" disabled={busy || isSafeMode}>
              <legend title="当原路径已存在其他文件或目录时系统的处理方式。系统严禁直接覆盖目标文件。">
                目标路径冲突处理策略
              </legend>
              <label className={conflictPolicy === 'skip' ? 'is-selected' : ''}>
                <input type="radio" name="restore-conflict-policy" value="skip"
                  checked={conflictPolicy === 'skip'}
                  onChange={() => setConflictPolicy('skip')} />
                <span><strong>跳过 (Skip - 默认)</strong>：若目标路径已存在同名实体，取消本次恢复，保持隔离状态不变。</span>
              </label>
              <label className={conflictPolicy === 'rename' ? 'is-selected' : ''}>
                <input type="radio" name="restore-conflict-policy" value="rename"
                  checked={conflictPolicy === 'rename'}
                  onChange={() => setConflictPolicy('rename')} />
                <span><strong>自动重命名 (Rename)</strong>：若原目标已被占用，自动保存为 <code>.restored-{entry.id}</code>，避免覆盖。</span>
              </label>
              <label className={conflictPolicy === 'manual' ? 'is-selected' : ''}>
                <input type="radio" name="restore-conflict-policy" value="manual"
                  checked={conflictPolicy === 'manual'}
                  onChange={() => setConflictPolicy('manual')} />
                <span><strong>指定目标路径 (Manual)</strong>：手动指定恢复目标绝对路径（必须在允许白名单目录内）。</span>
              </label>
            </fieldset>
            {conflictPolicy === 'manual' && (
              <label className="nfc-v2-quarantine-manual">
                <span>自定义恢复绝对路径</span>
                <input type="text" value={customTarget}
                  placeholder="例如: /data/restored_files/my_file.txt"
                  aria-invalid={!availability.canRestore && !isSafeMode}
                  disabled={isSafeMode || busy}
                  onChange={event => setCustomTarget(event.target.value)} />
                {!availability.canRestore && !isSafeMode &&
                  <span className="nfc-v2-quarantine-error" role="alert">{availability.reason}</span>}
              </label>
            )}
          </div>
          <div className="nfc-v2-confirm-actions">
            <ConsoleButton disabled={busy} onClick={closeSafely}>取消</ConsoleButton>
            <ConsoleButton variant="primary" loading={busy}
              disabled={!availability.canRestore || busy}
              onClick={() => { void handleConfirm(); }}>确认恢复</ConsoleButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
