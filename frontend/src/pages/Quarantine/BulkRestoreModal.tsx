import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { quarantineApi } from '../../api/quarantine';
import { getStructuredApiError } from '../../api/errors';
import type {
  QuarantineBulkConflictPolicy, QuarantineBulkPlanResponse, QuarantineBulkPreviewResponse,
} from '../../types';
import {
  getBulkRestoreAvailability, isBulkPreviewSelectionCurrent,
} from '../../components/quarantine/quarantine_rules';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

interface Props {
  open: boolean;
  entryIds: number[];
  isSafeMode: boolean;
  onClose: () => void;
  onPlanCreated: (plan: QuarantineBulkPlanResponse) => void;
}

/** Preview and Draft only. Actual restore is always Freeze → Validate → Execute. */
export const BulkRestoreModal: React.FC<Props> = ({
  open, entryIds, isSafeMode, onClose, onPlanCreated,
}) => {
  const toast = useConsoleToast();
  const [policy, setPolicy] = useState<QuarantineBulkConflictPolicy>('skip');
  const [preview, setPreview] = useState<QuarantineBulkPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const inFlight = useRef(false);
  const requestEpoch = useRef(0);

  const selectionKey = useMemo(() => [...entryIds].sort((a, b) => a - b).join(','), [entryIds]);
  const live = useRef({ open, selectionKey, policy, isSafeMode });
  live.current = { open, selectionKey, policy, isSafeMode };
  const availability = getBulkRestoreAvailability(isSafeMode, policy);
  const previewCurrent = Boolean(
    preview &&
      preview.action === 'restore' &&
      preview.items.every(item => item.conflict_policy === undefined || item.conflict_policy === policy) &&
      isBulkPreviewSelectionCurrent(preview.entry_ids, entryIds)
  );
  const canGenerate = Boolean(
    previewCurrent &&
      preview &&
      preview.blocked_count === 0 &&
      availability.canRestore &&
      !previewLoading &&
      !planLoading &&
      !inFlight.current
  );
  const busy = previewLoading || planLoading;

  useEffect(() => {
    requestEpoch.current += 1;
    if (open) {
      setPolicy('skip');
      setPreview(null);
    }
  }, [open, selectionKey]);

  const closeSafely = () => {
    if (!busy && !inFlight.current) onClose();
  };
  const handlePolicyChange = (value: QuarantineBulkConflictPolicy) => {
    if (busy || inFlight.current) return;
    requestEpoch.current += 1;
    setPolicy(value);
    setPreview(null);
  };
  const handlePreview = async () => {
    if (!open || busy || inFlight.current) return;
    if (entryIds.length === 0) {
      toast.info('请先选择至少一个 active 隔离条目');
      return;
    }
    if (!availability.canRestore) {
      toast.error(availability.reason || '当前状态禁止批量恢复');
      return;
    }
    const ids = [...entryIds];
    const requestKey = selectionKey;
    const requestPolicy = policy;
    const ticket = ++requestEpoch.current;
    const isCurrent = () => live.current.open && live.current.selectionKey === requestKey &&
      live.current.policy === requestPolicy && !live.current.isSafeMode &&
      requestEpoch.current === ticket;
    inFlight.current = true;
    setPreviewLoading(true);
    setPreview(null);
    try {
      const result = await quarantineApi.bulkPreview({
        action: 'restore', entry_ids: ids, conflict_policy: requestPolicy,
      });
      if (!isCurrent()) return;
      if (result.action !== 'restore' ||
          !isBulkPreviewSelectionCurrent(result.entry_ids, ids) ||
          result.items.some(item => item.conflict_policy !== undefined && item.conflict_policy !== requestPolicy) ||
          !result.preview_digest) {
        toast.error('Preview 身份或冲突策略不一致，请重新 Preview');
        return;
      }
      setPreview(result);
      if (result.blocked_count > 0) {
        toast.info('Preview 完成：' + result.blocked_count + ' 个条目被安全阻断，不能生成 Draft');
      } else {
        // Inline status below is already announced; discard a prior blocked
        // Preview toast so it cannot persist over another modal's controls.
        toast.dismiss();
      }
    } catch (error: unknown) {
      if (isCurrent()) toast.error(getStructuredApiError(error).message || '批量恢复 Preview 失败');
    } finally {
      inFlight.current = false;
      setPreviewLoading(false);
    }
  };
  const handleGenerateDraft = async () => {
    if (!open || busy || inFlight.current) return;
    if (!preview || !previewCurrent || !preview.preview_digest) {
      toast.info('选择或策略已变化，请重新 Preview');
      setPreview(null);
      return;
    }
    if (preview.blocked_count > 0) {
      toast.error('Preview 中存在 blocked 条目，按照 Gate6-A fail-closed 规则不能生成 Draft');
      return;
    }
    if (!availability.canRestore) {
      toast.error(availability.reason || '当前状态禁止批量恢复');
      return;
    }
    const snapshot = {
      action: 'restore' as const,
      entry_ids: [...preview.entry_ids],
      conflict_policy: policy,
      expected_preview_digest: preview.preview_digest,
    };
    const ticket = ++requestEpoch.current;
    inFlight.current = true;
    setPlanLoading(true);
    try {
      const plan = await quarantineApi.bulkPlan(snapshot);
      toast.success('批量恢复 Draft #' + plan.id + ' 已生成；尚未执行任何文件变更');
      onPlanCreated(plan);
    } catch (error: unknown) {
      if (requestEpoch.current === ticket) {
        setPreview(null);
        toast.error(getStructuredApiError(error).message || '生成批量恢复 Draft 失败；请重新 Preview');
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
          className="nfc-v2-dialog nfc-overlay-modal nfc-quarantine-bulk-restore-modal nfc-v2-quarantine-bulk-dialog"
          onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon"><ConsoleIcon name="archive" size={20} /></span>
            <div>
              <Dialog.Title>批量恢复 — 生成安全 Draft</Dialog.Title>
              <Dialog.Description className="nfc-v2-quarantine-bulk-description">
                先 Preview，再生成与预览摘要绑定的计划草稿；本窗口不会修改文件。
              </Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dialog-close" aria-label="关闭批量恢复窗口"
              disabled={busy} onClick={closeSafely}><ConsoleIcon name="x" size={18} /></button>
          </header>
          <div className="nfc-v2-quarantine-bulk-body">
            <div className="nfc-v2-quarantine-bulk-note" role="note">
              <ConsoleIcon name="info" size={18} />
              <div><strong>已明确选择 {entryIds.length} 个 active 条目</strong>
                <p>此窗口只执行 Preview 与 Draft 生成，不会直接恢复文件。Draft 生成后仍必须经过 Plan 的 Freeze → Validate → Execute。</p>
              </div>
            </div>
            {isSafeMode && <div className="nfc-v2-quarantine-bulk-note is-warning" role="alert">
              <ConsoleIcon name="lock" size={18} />
              <div><strong>ALLOW_MUTATION=false</strong>
                <p>当前只读安全模式禁止生成可执行的批量恢复计划。</p>
              </div>
            </div>}
            <fieldset className="nfc-v2-quarantine-bulk-options" disabled={busy || isSafeMode}>
              <legend>冲突处理</legend>
              <label className={policy === 'skip' ? 'is-selected' : ''}>
                <input type="radio" name="bulk-restore-policy" value="skip"
                  checked={policy === 'skip'} onChange={() => handlePolicyChange('skip')} />
                <span>跳过（默认）— 目标已存在时保留隔离条目，不覆盖</span>
              </label>
              <label className={policy === 'rename' ? 'is-selected' : ''}>
                <input type="radio" name="bulk-restore-policy" value="rename"
                  checked={policy === 'rename'} onChange={() => handlePolicyChange('rename')} />
                <span>自动重命名 — 使用服务端冻结的安全目标，不覆盖</span>
              </label>
            </fieldset>
            {!preview && <p className="nfc-v2-quarantine-bulk-help">
              先运行 Preview。任何 blocked 条目都会阻止整批 Draft 生成，不会静默丢弃成员。
            </p>}
            {preview && previewCurrent && (
              <section className="nfc-v2-quarantine-bulk-results" aria-label="批量恢复预览结果">
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
                      <li key={item.entry_id}>#{item.entry_id}: {item.reason || 'blocked'}</li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </div>
          <div className="nfc-v2-confirm-actions">
            <ConsoleButton onClick={closeSafely} disabled={busy}>取消</ConsoleButton>
            <ConsoleButton onClick={() => { void handlePreview(); }} loading={previewLoading}
              disabled={!availability.canRestore || busy || entryIds.length === 0}>
              重新 Preview
            </ConsoleButton>
            <ConsoleButton variant="primary" onClick={() => { void handleGenerateDraft(); }}
              loading={planLoading} disabled={!canGenerate || busy}>
              生成 Draft
            </ConsoleButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
