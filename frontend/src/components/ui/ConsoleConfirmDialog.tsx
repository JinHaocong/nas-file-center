import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ConsoleButton } from './ConsoleButton';
import { ConsoleIcon } from './ConsoleIcon';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: React.ReactNode;
  confirmText: string;
  onConfirm: () => void;
  busy?: boolean;
  disabled?: boolean;
  danger?: boolean;
}

/** Explicit destructive confirmation. Never dismiss an in-flight request. */
export const ConsoleConfirmDialog: React.FC<Props> = ({
  open, onOpenChange, title, description, confirmText, onConfirm,
  busy = false, disabled = false, danger = true,
}) => (
  <Dialog.Root open={open} onOpenChange={next => {
    if (!busy) onOpenChange(next);
  }}>
    <Dialog.Portal>
      <Dialog.Overlay className="nfc-v2-dialog-overlay" />
      <Dialog.Content
        className="nfc-v2-dialog nfc-v2-confirm-dialog nfc-overlay-modal"
        onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
        onPointerDownOutside={event => event.preventDefault()}
      >
        <header className="nfc-v2-dialog-heading">
          <span className={'nfc-v2-dialog-icon' + (danger ? ' is-danger' : '')}>
            <ConsoleIcon name="shield-check" size={20} />
          </span>
          <div>
            <Dialog.Title>{title}</Dialog.Title>
          </div>
          <button type="button" className="nfc-v2-dialog-close"
            aria-label="关闭确认窗口" disabled={busy}
            onClick={() => onOpenChange(false)}>
            <ConsoleIcon name="x" size={18} />
          </button>
        </header>
        <Dialog.Description asChild>
          <div className="nfc-v2-confirm-description">{description}</div>
        </Dialog.Description>
        <div className="nfc-v2-confirm-actions">
          <ConsoleButton disabled={busy} onClick={() => onOpenChange(false)}>取消</ConsoleButton>
          <ConsoleButton variant={danger ? 'danger' : 'primary'}
            disabled={busy || disabled} loading={busy} onClick={onConfirm}>
            {confirmText}
          </ConsoleButton>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
);
