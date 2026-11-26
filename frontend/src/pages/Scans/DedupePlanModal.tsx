import React, { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import type { ScanId } from '../../types';
import { sqliteIdText } from '../../utils/sqliteId';
import { scansApi } from '../../api/domain';
import { POLICY_OPTIONS } from '../../utils/constants';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import {
  type ClassicDedupeValues, type ClassicDedupePayload,
  defaultClassicDedupeValues, toClassicDedupePayload, validateClassicDedupe,
} from './classic_dedupe_form';

interface Props {
  scanId: ScanId;
  open: boolean;
  onClose: () => void;
}

export const DedupePlanModal: React.FC<Props> = ({ scanId, open, onClose }) => {
  const [values, setValues] = useState<ClassicDedupeValues>(defaultClassicDedupeValues);
  const [error, setError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const openerRef = useRef<HTMLElement | null>(null);
  const policyField = useRef<HTMLSelectElement>(null);
  const navigate = useNavigate();
  const toast = useConsoleToast();

  const planMutation = useMutation({
    mutationFn: (payload: ClassicDedupePayload) => scansApi.createDedupePlan(scanId, payload),
    onSuccess: res => {
      submittingRef.current = false;
      toast.success('已成功创建去重计划 #' + res.id);
      onClose();
      navigate('/plans/' + res.id);
    },
    onError: (err: Error) => {
      submittingRef.current = false;
      const message = err.message || '生成计划失败';
      setError(message);
      toast.error(message);
    },
  });

  useEffect(() => {
    if (!open) return;
    setValues(defaultClassicDedupeValues());
    setError(null);
    submittingRef.current = false;
    planMutation.reset();
    // Reset only on opening, not on re-renders caused by the mutation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scanId]);

  const busy = planMutation.isPending;
  const close = () => {
    if (busy || submittingRef.current) return;
    setError(null);
    onClose();
  };

  const change = <K extends keyof ClassicDedupeValues>(key: K, value: ClassicDedupeValues[K]) => {
    setValues(previous => ({ ...previous, [key]: value }));
    setError(null);
  };

  const handleCreate = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || submittingRef.current) return;
    const failure = validateClassicDedupe(values);
    if (failure) {
      setError(failure);
      return;
    }
    if (!sqliteIdText(scanId)) {
      setError('扫描任务 ID 无效');
      return;
    }
    submittingRef.current = true;
    setError(null);
    planMutation.mutate(toClassicDedupePayload(values));
  };

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) close(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-dedupe-overlay" />
        <Dialog.Content className="nfc-overlay-modal nfc-dedupe-plan-modal nfc-v2-dedupe-dialog nfc-record-dialog"
          data-form-dialog aria-busy={busy || undefined}
          onOpenAutoFocus={event => {
            const active = document.activeElement;
            openerRef.current = active instanceof HTMLElement && active !== document.body ? active : null;
            if (!policyField.current) return;
            event.preventDefault();
            policyField.current.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={event => {
            const opener = openerRef.current;
            openerRef.current = null;
            if (!opener?.isConnected || opener.matches(':disabled') || !opener.getClientRects().length) return;
            event.preventDefault();
            opener.focus({ preventScroll: true });
          }}
          onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dedupe-dialog-header" data-form-dialog-header>
            <div>
              <Dialog.Title>生成经典去重计划</Dialog.Title>
              <Dialog.Description>只生成草稿计划，不会直接删除或修改任何文件。</Dialog.Description>
            </div>
            <button type="button" aria-label="关闭经典去重计划窗口"
              className="nfc-v2-dedupe-close" disabled={busy} onClick={close}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>

          <form className="nfc-dedupe-plan-form nfc-v2-dedupe-form" onSubmit={handleCreate}>
            <div data-form-dialog-body>
              <div className="nfc-v2-dedupe-note" role="note">
                <ConsoleIcon name="shield-check" size={18} />
                <span><strong>扫描 #{scanId}</strong> · 使用单一保留策略生成草稿。加权评分、实时预览和成员选择理由可在「高级精确去重」中查看。</span>
              </div>
              <div className="nfc-v2-dedupe-field">
                <label htmlFor="nfc-classic-policy">保留策略</label>
                <select id="nfc-classic-policy" ref={policyField} value={values.policy} disabled={busy}
                  onChange={event => change('policy', event.target.value)}>
                  {POLICY_OPTIONS.map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              {values.policy === 'path-priority' && (
                <div className="nfc-v2-dedupe-field">
                  <label htmlFor="nfc-classic-path-priority">完整路径优先级模式（每行一个规则）</label>
                  <textarea id="nfc-classic-path-priority" rows={4} required
                    placeholder={'/data/Photos/Master/*\n/data/Backup/*'}
                    value={values.pathPriorityText} disabled={busy}
                    onChange={event => change('pathPriorityText', event.target.value)} />
                </div>
              )}
              {values.policy === 'relative-path-preference' && (
                <div className="nfc-v2-dedupe-field">
                  <label htmlFor="nfc-classic-relative-priority">相对路径优先级模式（每行一个规则）</label>
                  <textarea id="nfc-classic-relative-priority" rows={4} required
                    placeholder={'Originals/*\nSorted/*'}
                    value={values.relativePathPriorityText} disabled={busy}
                    onChange={event => change('relativePathPriorityText', event.target.value)} />
                </div>
              )}
              <p className="nfc-v2-dedupe-safety">
                <ConsoleIcon name="shield-check" size={16} />
                安全保障：系统只生成待审阅的草稿计划；后续须经过 Freeze → Validate → Execute 与 SHA256 校验。
              </p>
              {error && <div className="nfc-v2-dedupe-error" role="alert">{error}</div>}
            </div>
            <footer className="nfc-v2-dedupe-actions" data-form-dialog-actions>
              <ConsoleButton disabled={busy} onClick={close}>取消</ConsoleButton>
              <ConsoleButton type="submit" variant="primary" loading={busy}
                leadingIcon={<ConsoleIcon name="check-circle" size={16} />}>生成计划草稿</ConsoleButton>
            </footer>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
