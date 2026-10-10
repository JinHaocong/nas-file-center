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
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<OrganizerProfileSnapshot>(() => initialOrganizerProfileForm(editingProfile));
  const [submitted, setSubmitted] = useState(false);

  // Reset on each open/profile identity, same as Ant Form resetFields + setFieldsValue.
  useEffect(() => {
    if (!open) return;
    setDraft(initialOrganizerProfileForm(editingProfile));
    setSubmitted(false);
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
  const save = async () => {
    setSubmitted(true);
    if (!canSubmitOrganizerProfileForm(draft, editingProfile, busy || savingRef.current)) return;
    savingRef.current = true;
    setSaving(true);
    try {
      await onSubmit(organizerProfileFormPayload(draft));
    } catch {
      // The owning mutation exposes the server validation error via toast.
      // Keep the dialog and draft intact for correction.
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
          onEscapeKeyDown={event => { if (busy || savingRef.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-organizer-profile-heading">
            <div>
              <Dialog.Title>{editingProfile ? '编辑方案: ' + editingProfile.name : '新建整理方案'}</Dialog.Title>
              <Dialog.Description>配置方案仅存储规则；文件更改必须经过只读 Preview 和 Plan 安全检查。</Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-organizer-profile-close"
              aria-label="关闭整理方案编辑" disabled={busy} onClick={close}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>
          <form className="nfc-v2-organizer-profile-form" id={id} noValidate
            onSubmit={event => { event.preventDefault(); void save(); }}>
            <div className="nfc-v2-organizer-profile-body">
              <OrganizerSnapshotFields includeRoot value={draft} onChange={setDraft} readOnly={busy || !!editingProfile?.is_builtin} />
              {submitted && errors.length > 0 && (
                <div role="alert" className="nfc-v2-organizer-profile-errors">
                  <strong>请修正以下配置问题后再保存</strong>
                  {errors.map(error => <p key={error}>{error}</p>)}
                </div>
              )}
              {!!editingProfile?.is_builtin && (
                <div role="alert" className="nfc-v2-organizer-profile-errors">
                  内置方案不可直接编辑，请先复制为个人方案。
                </div>
              )}
            </div>
            <footer className="nfc-v2-organizer-profile-actions">
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
