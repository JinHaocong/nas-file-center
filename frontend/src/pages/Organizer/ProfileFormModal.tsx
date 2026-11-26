import React, { useEffect, useId, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import type { OrganizerProfile } from '../../types';
import type { OrganizerProfileSnapshot } from '../../types/workflow';
import { OrganizerSnapshotFields } from '../../components/workflows/OrganizerSnapshotFields';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { validateWorkflowOrganizerSnapshot } from '../../utils/workflowOrganizerSnapshot';
import {
  canSubmitOrganizerProfileForm, initialOrganizerProfileForm,
  organizerProfileFormPayload,
} from '../../utils/organizerProfileForm';

interface Props {
  open: boolean;
  editingProfile: OrganizerProfile | null;
  onCancel: () => void;
  onSubmit: (values: Partial<OrganizerProfile>) => Promise<void>;
  loading?: boolean;
}

/** Organizer profile CRUD form only; Preview and Plan remain separate server-authorized flows. */
export const ProfileFormModal: React.FC<Props> = ({
  open, editingProfile, onCancel, onSubmit, loading = false,
}) => {
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<OrganizerProfileSnapshot>(() => initialOrganizerProfileForm(editingProfile));
  const [saveError, setSaveError] = useState<string | null>(null);

  // Reset on each open/profile identity, same as Ant Form resetFields + setFieldsValue.
  useEffect(() => {
    if (!open) return;
    setDraft(initialOrganizerProfileForm(editingProfile));
    setSaveError(null);
    savingRef.current = false;
    setSaving(false);
  }, [open, editingProfile?.id]);

  const busy = loading || saving;
  const errors = validateWorkflowOrganizerSnapshot(draft);
  const canSave = canSubmitOrganizerProfileForm(draft, editingProfile, busy || savingRef.current);

  const close = () => {
    if (busy || savingRef.current) return;
    onCancel();
  };
  /** Keep server feedback tied to the draft that was submitted. */
  const updateDraft = (value: OrganizerProfileSnapshot) => {
    if (busy || savingRef.current) return;
    setDraft(value);
    setSaveError(null);
  };
  const save = async () => {
    if (!canSubmitOrganizerProfileForm(draft, editingProfile, busy || savingRef.current)) return;
    savingRef.current = true;
    setSaving(true);
    setSaveError(null);
    try {
      await onSubmit(organizerProfileFormPayload(draft));
    } catch (failure: unknown) {
      setSaveError(failure instanceof Error ? failure.message : '保存整理方案失败');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) close(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-organizer-profile-overlay" />
        <Dialog.Content className="nfc-v2-organizer-profile-dialog nfc-overlay-modal"
          data-form-dialog aria-busy={busy || undefined}
          onOpenAutoFocus={event => {
            const active = document.activeElement;
            openerRef.current = active instanceof HTMLElement && active !== document.body ? active : null;
            const field = formRef.current?.querySelector<HTMLInputElement>('input[type=text]:enabled');
            if (!field) return;
            event.preventDefault();
            field.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={event => {
            const opener = openerRef.current;
            openerRef.current = null;
            if (!opener?.isConnected || opener.matches(':disabled') || !opener.getClientRects().length) return;
            event.preventDefault();
            opener.focus({ preventScroll: true });
          }}
          onEscapeKeyDown={event => { if (busy || savingRef.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-organizer-profile-heading" data-form-dialog-header>
            <div>
              <Dialog.Title>{editingProfile ? '编辑方案 · ' + editingProfile.name : '新建整理方案'}</Dialog.Title>
              <Dialog.Description>保存后会更新方案配置。文件改动需先预览，再生成执行计划。</Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-organizer-profile-close"
              aria-label="关闭整理方案编辑" disabled={busy} onClick={close}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>
          <form className="nfc-v2-organizer-profile-form" id={id} ref={formRef} noValidate
            onSubmit={event => { event.preventDefault(); void save(); }}>
            <div className="nfc-v2-organizer-profile-body" data-form-dialog-body>
              {!!editingProfile?.is_builtin && (
                <div role="alert" className="nfc-v2-organizer-profile-errors">
                  内置方案不可直接编辑，请先复制为个人方案。
                </div>
              )}
              <OrganizerSnapshotFields includeRoot value={draft} onChange={updateDraft} readOnly={busy || !!editingProfile?.is_builtin} />
              {saveError && <div role="alert" className="nfc-v2-organizer-profile-errors">{saveError}</div>}
            </div>
            <footer className="nfc-v2-organizer-profile-actions" data-form-dialog-actions>
              {errors.length > 0 && !editingProfile?.is_builtin && (
                <span className="nfc-form-dialog-status" role="status">{errors.length} 项配置需修正</span>
              )}
              <ConsoleButton disabled={busy} onClick={close}>取消</ConsoleButton>
              <ConsoleButton type="submit" variant="primary" loading={busy}
                disabled={!canSave}>保存方案</ConsoleButton>
            </footer>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
