import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { quarantineApi } from '../../api/quarantine';
import { getStructuredApiError } from '../../api/errors';
import type { QuarantineBulkPlanResponse, QuarantineBulkPreviewResponse } from '../../types';
import {
  getQuarantinePurgeAvailability, isBulkPreviewSelectionCurrent,
} from '../../components/quarantine/quarantine_rules';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

interface Props {
  open: boolean;
  entryIds: number[];
  isAdmin: boolean;
  allowMutation: boolean;
  allowDelete: boolean;
  onClose: () => void;
  onPlanCreated: (plan: QuarantineBulkPlanResponse) => void;
}

const Advisory: React.FC<{
  tone?: 'warning' | 'success' | 'info' | 'danger';
  title: string;
  children?: React.ReactNode;
}> = ({ tone = 'info', title, children }) => (
  <div className={'nfc-v2-quarantine-bulk-note is-' + tone}
    role={tone === 'danger' ? 'alert' : 'note'}>
    <ConsoleIcon name={tone === 'warning' || tone === 'danger' ? 'shield-check' : 'info'} size={18} />
    <div><strong>{title}</strong>{children && <div className="nfc-v2-quarantine-bulk-copy">{children}</div>}</div>
  </div>
);

/** Never unlinks files here: even a digest-bound DELETE only creates a Draft. */
export const BulkPurgeModal: React.FC<Props> = ({
  open, entryIds, isAdmin, allowMutation, allowDelete, onClose, onPlanCreated,
}) => {
  const toast = useConsoleToast();
  const [confirmInput, setConfirmInput] = useState('');
  const [preview, setPreview] = useState<QuarantineBulkPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const inFlight = useRef(false);
  const requestEpoch = useRef(0);

  const selectionKey = useMemo(() => [...entryIds].sort((a, b) => a - b).join(','), [entryIds]);
  const live = useRef({ open, selectionKey, isAdmin, allowMutation, allowDelete });
  live.current = { open, selectionKey, isAdmin, allowMutation, allowDelete };
  const canPurge = getQuarantinePurgeAvailability(isAdmin, allowDelete, allowMutation).canPurge;
  const previewCurrent = Boolean(
    preview && preview.action === 'purge' &&
      isBulkPreviewSelectionCurrent(preview.entry_ids, entryIds) &&
      preview.preview_digest
  );
  const isConfirmed = confirmInput === 'DELETE';
  const canGenerate = Boolean(
    canPurge &&
      isConfirmed &&
      previewCurrent &&
      preview &&
      preview.blocked_count === 0 &&
      !previewLoading &&
      !planLoading &&
      !inFlight.current
  );
  const busy = previewLoading || planLoading;

  useEffect(() => {
    requestEpoch.current += 1;
    if (open) {
      setConfirmInput('');
      setPreview(null);
    }
  }, [open, selectionKey]);

  const closeSafely = () => {
    if (!busy && !inFlight.current) onClose();
  };
  const handlePreview = async () => {
    if (!open || busy || inFlight.current) return;
    if (entryIds.length === 0) {
      toast.info('请先选择至少一个 active 隔离条目');
      return;
    }
    if (!canPurge) {
      toast.error('当前管理员权限或服务端安全开关禁止批量永久删除');
      return;
    }
    const ids = [...entryIds];
    const requestKey = selectionKey;
    const ticket = ++requestEpoch.current;
    const isCurrent = () => live.current.open && live.current.selectionKey === requestKey &&
      live.current.isAdmin && live.current.allowMutation && live.current.allowDelete &&
      requestEpoch.current === ticket;
    inFlight.current = true;
    setPreviewLoading(true);
    setPreview(null);
    setConfirmInput('');
    try {
      const result = await quarantineApi.bulkPreview({
        action: 'purge', entry_ids: ids,
      });
      if (!isCurrent()) return;
      if (result.action !== 'purge' ||
          !isBulkPreviewSelectionCurrent(result.entry_ids, ids) ||
          !result.preview_digest) {
        toast.error('Preview 身份不一致，请重新 Preview');
        return;
      }
      setPreview(result);
      if (result.blocked_count > 0) {
        toast.info('Preview 完成：' + result.blocked_count + ' 个条目被安全阻断，不能生成 Draft');
      }
      // The eligible/blocked/digest summary below announces success inline.
      // A floating success toast overlaps the exact DELETE input on mobile.
    } catch (error: unknown) {
      if (isCurrent()) toast.error(getStructuredApiError(error).message || '批量永久删除 Preview 失败');
    } finally {
      inFlight.current = false;
      setPreviewLoading(false);
    }
  };
  const handleGenerateDraft = async () => {
    if (!open || busy || inFlight.current) return;
    if (!preview || !previewCurrent || !preview.preview_digest) {
      toast.info('选择或 Preview 身份已变化，请重新 Preview');
      setPreview(null);
      setConfirmInput('');
      return;
    }
    if (preview.blocked_count > 0) {
      toast.error('Preview 中存在 blocked 条目，按照 fail-closed 规则不能生成 Draft');
      return;
    }
    const allowed = getQuarantinePurgeAvailability(
      isAdmin, allowDelete, allowMutation, confirmInput,
    );
    if (!allowed.canPurge) {
      toast.error(allowed.reason || '当前管理员权限或服务端安全开关禁止批量永久删除');
      return;
    }
    const snapshot = {
      action: 'purge' as const,
      entry_ids: [...preview.entry_ids],
      expected_preview_digest: preview.preview_digest,
      confirmation: 'DELETE' as const,
    };
    const ticket = ++requestEpoch.current;
    inFlight.current = true;
    setPlanLoading(true);
    try {
      const plan = await quarantineApi.bulkPlan(snapshot);
      toast.success('批量永久删除 Draft #' + plan.id + ' 已生成；尚未删除任何文件');
      onPlanCreated(plan);
    } catch (error: unknown) {
      if (requestEpoch.current === ticket) {
        setPreview(null);
        setConfirmInput('');
        toast.error(getStructuredApiError(error).message ||
          '生成批量永久删除 Draft 失败；请重新 Preview 并重新确认');
      }
    } finally {
      inFlight.current = false;
      setPlanLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) closeSafely(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
        <Dialog.Content
          className="nfc-v2-dialog nfc-overlay-modal nfc-quarantine-bulk-purge-modal nfc-v2-quarantine-bulk-dialog"
          onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon is-danger"><ConsoleIcon name="trash" size={20} /></span>
            <div>
              <Dialog.Title>批量永久删除 — 生成安全 Draft</Dialog.Title>
              <Dialog.Description className="nfc-v2-quarantine-bulk-description">
                此操作要求管理员确认，当前窗口只生成 Draft，不直接清除文件。
              </Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dialog-close" aria-label="关闭批量清除窗口"
              disabled={busy} onClick={closeSafely}><ConsoleIcon name="x" size={18} /></button>
          </header>
          <div className="nfc-v2-quarantine-bulk-body">
            {!isAdmin && <Advisory tone="danger" title="仅系统管理员允许批量永久删除" />}
            {!allowMutation && <Advisory tone="warning" title="ALLOW_MUTATION=false" />}
            {!allowDelete && <Advisory tone="warning" title="ALLOW_DELETE=false" />}
            <Advisory tone="danger" title={'不可逆操作：已明确选择 ' + entryIds.length + ' 个 active 条目'}>
              <p>此窗口只生成当前 Preview digest 对应的 Draft。真正执行仍必须经过 Freeze → Validate → Execute。执行语义是普通文件删除（unlink）：只移除 NFC 拥有并已冻结的隔离区路径，不覆盖文件内容，也不承诺安全擦除。</p>
            </Advisory>
            {!preview && (
              <p className="nfc-v2-quarantine-bulk-help">
                先运行 Preview。服务端会重新核验每个选中条目的状态、持久化身份与 unlink_v1 pathname authority；任一 mutation blocker 都会阻止整批 Draft。索引范围内的 hard link 与同内容独立副本仅作为 advisory，不会扩大或改变删除权限。
              </p>
            )}
            {preview && previewCurrent && (
              <section className="nfc-v2-quarantine-bulk-results" aria-label="批量清除预览结果">
                <div className="nfc-v2-quarantine-bulk-metrics" role="status" aria-live="polite">
                  <span>Eligible {preview.eligible_count}</span>
                  <span className={preview.blocked_count ? 'is-blocked' : 'is-allowed'}>
                    Blocked {preview.blocked_count}
                  </span>
                  <code>Digest: {preview.preview_digest.slice(0, 16)}…</code>
                </div>
                {preview.blocked_count > 0 && (
                  <ul className="nfc-v2-quarantine-bulk-blocked">
                    {preview.items.filter(item => !item.eligible).map(item => (
                      <li key={item.entry_id}>
                        #{item.entry_id}: {item.reason || 'blocked'}
                        {item.mutation_blockers?.length ? ' (' + item.mutation_blockers.join(', ') + ')' : ''}
                      </li>
                    ))}
                  </ul>
                )}
                {preview.items.filter(item => item.eligible && item.purge_semantics === 'unlink_v1')
                  .map(item => (
                    <article className="nfc-quarantine-preview-card nfc-v2-quarantine-bulk-card" key={item.entry_id}>
                      <strong>#{item.entry_id} · 普通文件删除（unlink_v1）</strong>
                      {item.survivor_status === 'found' ? (
                        <Advisory tone="warning" title="当前隔离副本可清除，但索引范围内仍发现存活 hard link">
                          <ul>{(item.hardlink_survivor_paths || []).map(path => (
                            <li key={path}><code>{path}</code></li>
                          ))}</ul>
                        </Advisory>
                      ) : item.survivor_status === 'incomplete' ? (
                        <Advisory tone="warning" title="索引范围内 hard link 检查不完整">
                          {(item.advisory_diagnostics || []).join('; ') ||
                            '部分候选路径无法完成 live lstat 核验；这只是 advisory，不改变当前 unlink 权限。'}
                        </Advisory>
                      ) : (
                        <Advisory tone="success" title="索引范围内未发现存活 hard link">
                          检查范围：{item.survivor_scope || 'indexed_roots_only'}
                        </Advisory>
                      )}
                      {(item.independent_copy_paths?.length || 0) > 0 && (
                        <Advisory title="发现同内容但不同 inode 的独立副本">
                          <ul>{(item.independent_copy_paths || []).map(path => (
                            <li key={path}><code>{path}</code></li>
                          ))}</ul>
                        </Advisory>
                      )}
                    </article>
                  ))}
                {preview.blocked_count === 0 && (
                  <label className="nfc-destructive-confirm nfc-v2-quarantine-bulk-token">
                    <span className="nfc-destructive-confirm-copy">
                      Preview 已冻结当前批次。hard-link survivor / 独立副本只是提示，不属于 mutation authority。若确认生成 Draft，请输入大写 <code className="nfc-danger-text">DELETE</code>：
                    </span>
                    <input type="text" value={confirmInput} autoComplete="off" spellCheck={false}
                      onChange={event => setConfirmInput(event.target.value)}
                      placeholder="请输入 DELETE"
                      aria-invalid={!!confirmInput && !isConfirmed}
                      disabled={!canPurge || busy} />
                    {confirmInput && !isConfirmed && (
                      <span className="nfc-v2-quarantine-bulk-error" role="alert">必须严格输入全大写 DELETE</span>
                    )}
                  </label>
                )}
              </section>
            )}
          </div>
          <div className="nfc-v2-confirm-actions">
            <ConsoleButton onClick={closeSafely} disabled={busy}>取消</ConsoleButton>
            <ConsoleButton onClick={() => { void handlePreview(); }} loading={previewLoading}
              disabled={!canPurge || busy || entryIds.length === 0}>
              重新 Preview
            </ConsoleButton>
            <ConsoleButton variant="danger" leadingIcon={<ConsoleIcon name="trash" size={16} />}
              onClick={() => { void handleGenerateDraft(); }} loading={planLoading}
              disabled={!canGenerate || busy}>生成永久删除 Draft</ConsoleButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
