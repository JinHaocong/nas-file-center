import React, { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quarantineApi } from '../../api/quarantine';
import { getStructuredApiError } from '../../api/errors';
import type { QuarantineEntry, QuarantinePurgeResponse } from '../../types';
import { getQuarantinePurgeAvailability } from '../../components/quarantine/quarantine_rules';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { formatBytes } from '../../utils/format';

interface Props {
  entry: QuarantineEntry | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isAdmin: boolean;
  allowMutation: boolean;
  allowDelete: boolean;
}

const Notice: React.FC<{
  tone: 'info' | 'warning' | 'danger' | 'success';
  title: string;
  children: React.ReactNode;
}> = ({ tone, title, children }) => (
  <div className={'nfc-v2-quarantine-alert is-' + tone}
    role={tone === 'danger' ? 'alert' : 'note'}>
    <ConsoleIcon name={tone === 'danger' || tone === 'warning' ? 'shield-check' : 'info'} size={18} />
    <div><strong>{title}</strong><div className="nfc-v2-quarantine-alert-copy">{children}</div></div>
  </div>
);

/** Exact DELETE token + RBAC + both host switches; never overwrites or wipes hardlinked files. */
export const PurgeConfirmModal: React.FC<Props> = ({
  entry, open, onClose, onSuccess, isAdmin, allowMutation, allowDelete,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const inFlight = useRef(false);
  const [confirmInput, setConfirmInput] = useState('');
  const [purgeResult, setPurgeResult] = useState<QuarantinePurgeResponse | null>(null);

  useEffect(() => {
    if (open && !inFlight.current) {
      setConfirmInput('');
      setPurgeResult(null);
    }
  }, [open, entry?.id]);

  const purgeMutation = useMutation({
    mutationFn: () => {
      if (!entry) throw new Error('隔离条目不存在');
      const availability = getQuarantinePurgeAvailability(
        isAdmin, allowDelete, allowMutation, confirmInput,
      );
      if (!availability.canPurge) throw new Error(availability.reason || '永久清除操作不被允许');
      return quarantineApi.purge(entry.id, { confirmation: 'DELETE' });
    },
    onSuccess: result => {
      setPurgeResult(result);
      toast.success('隔离文件 #' + entry?.id + ' 已按普通文件删除（unlink）语义清除');
      void queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      onSuccess();
    },
    onError: (error: unknown) =>
      toast.error(getStructuredApiError(error).message || '清除隔离文件失败'),
  });

  const busy = purgeMutation.isPending;
  const availability = getQuarantinePurgeAvailability(
    isAdmin, allowDelete, allowMutation, confirmInput,
  );
  const closeSafely = () => { if (!busy && !inFlight.current) onClose(); };
  const handleConfirm = async () => {
    if (!entry || !open || busy || inFlight.current || purgeResult) return;
    const checked = getQuarantinePurgeAvailability(isAdmin, allowDelete, allowMutation, confirmInput);
    if (!checked.canPurge) { toast.error(checked.reason || '永久清除操作不被允许'); return; }
    inFlight.current = true;
    try { await purgeMutation.mutateAsync(); }
    catch { /* onError has surfaced the result; keep the dialog open to retry. */ }
    finally { inFlight.current = false; }
  };

  if (!entry) return null;
  const survivorPaths = purgeResult?.hardlink_survivor_paths || [];
  const independentCopyPaths = purgeResult?.independent_copy_paths || [];

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) closeSafely(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
        <Dialog.Content
          className="nfc-v2-dialog nfc-overlay-modal nfc-quarantine-purge-modal nfc-v2-quarantine-dialog"
          onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon is-danger"><ConsoleIcon name="trash" size={20} /></span>
            <div>
              <Dialog.Title>永久清除文件 #{entry.id}（普通文件删除）</Dialog.Title>
              <Dialog.Description className="nfc-v2-quarantine-subtitle">
                仅对 NFC 拥有且通过身份核验的隔离区 pathname 执行普通 unlink；这是不可撤销的操作。
              </Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dialog-close" aria-label="关闭清除窗口"
              disabled={busy} onClick={closeSafely}><ConsoleIcon name="x" size={18} /></button>
          </header>
          <div className="nfc-v2-quarantine-body">
            {!isAdmin && <Notice tone="danger" title="权限不足">
              只有系统管理员 (admin) 允许执行隔离文件的永久清除操作。
            </Notice>}
            {!allowMutation && <Notice tone="warning" title="只读安全模式生效中 (ALLOW_MUTATION=false)">
              系统当前处于只读保护模式，禁止执行任何永久清除操作。
            </Notice>}
            {!allowDelete && <Notice tone="warning" title="系统永久删除保护已开启 (ALLOW_DELETE=false)">
              服务端配置已禁用永久文件删除。需要由系统管理员明确开启 ALLOW_DELETE 后才能继续。
            </Notice>}
            {!purgeResult && <Notice tone="danger" title="不可逆的文件系统删除">
              此操作使用普通文件删除（unlink）语义，只删除 NFC 拥有并经过身份核验的隔离区路径；
              不会覆盖文件内容，也不会扩大到同 inode 的外部 hard link。若仍有其他 hard link，
              底层数据仍会被那些路径引用。
            </Notice>}

            <dl className="nfc-v2-quarantine-facts">
              <div><dt>原始路径</dt><dd><code className="nfc-breakall">{entry.original_path}</code></dd></div>
              <div><dt>隔离区路径</dt><dd><code className="nfc-breakall">{entry.quarantine_path}</code></dd></div>
              <div><dt>文件大小</dt><dd>{formatBytes(entry.size)}</dd></div>
            </dl>

            {purgeResult ? (
              <div className="nfc-quarantine-preview-stack nfc-v2-quarantine-results">
                <Notice tone="success" title={'隔离区路径已清除 · ' + (purgeResult.purge_semantics || 'unlink_v1')}>
                  已移除 {purgeResult.removed_count ?? 0} 个 NFC-owned pathname；
                  survivor_scope={purgeResult.survivor_scope || 'indexed_roots_only'}
                </Notice>
                {purgeResult.survivor_status === 'found' ? (
                  <Notice tone="warning" title="当前隔离副本已清除，但索引范围内仍发现存活 hard link">
                    <ul>{survivorPaths.map(path => <li key={path}><code>{path}</code></li>)}</ul>
                  </Notice>
                ) : purgeResult.survivor_status === 'incomplete' ? (
                  <Notice tone="warning" title="隔离区路径已清除，但索引范围内 hard link 核验不完整">
                    advisory 查询不完整不会改变已经完成的 unlink 结果。
                  </Notice>
                ) : (
                  <Notice tone="info" title="索引范围内未发现存活 hard link">
                    检查状态：{purgeResult.survivor_status || 'none_found'}
                  </Notice>
                )}
                {independentCopyPaths.length > 0 && (
                  <Notice tone="info" title="发现同内容但不同 inode 的独立副本">
                    <ul>{independentCopyPaths.map(path => <li key={path}><code>{path}</code></li>)}</ul>
                  </Notice>
                )}
              </div>
            ) : (
              <label className="nfc-destructive-confirm nfc-v2-quarantine-token">
                <span className="nfc-destructive-confirm-copy">
                  安全防呆核验：如确需永久删除，请在下方文本框中输入大写的 <code className="nfc-danger-text">DELETE</code>：
                </span>
                <input type="text" autoComplete="off" spellCheck={false}
                  placeholder="请输入 DELETE" value={confirmInput}
                  aria-invalid={confirmInput.length > 0 && !availability.canPurge}
                  disabled={!isAdmin || !allowMutation || !allowDelete || busy}
                  onChange={event => setConfirmInput(event.target.value)} />
                {confirmInput && confirmInput !== 'DELETE' && (
                  <span className="nfc-v2-quarantine-error" role="alert">必须严格输入全大写字母 "DELETE"</span>
                )}
              </label>
            )}
          </div>
          <div className="nfc-v2-confirm-actions">
            {!purgeResult && <ConsoleButton disabled={busy} onClick={closeSafely}>取消</ConsoleButton>}
            {purgeResult ? (
              <ConsoleButton variant="primary" onClick={closeSafely}>关闭</ConsoleButton>
            ) : (
              <ConsoleButton variant="danger" loading={busy}
                disabled={!availability.canPurge || busy}
                onClick={() => { void handleConfirm(); }}>永久清除 (unlink)</ConsoleButton>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
