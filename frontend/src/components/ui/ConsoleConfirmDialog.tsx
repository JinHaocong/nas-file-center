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
}) => {
  // Controlled dialogs have no Dialog.Trigger: remember the actual keyboard
  // opener before Radix moves focus into the confirmation portal.
  const returnFocusTarget = React.useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={next => {
      if (!busy) onOpenChange(next);
    }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
        <Dialog.Content
          className="nfc-v2-dialog nfc-v2-confirm-dialog nfc-overlay-modal"
          onOpenAutoFocus={() => {
            const active = document.activeElement;
            returnFocusTarget.current = active instanceof HTMLElement && active !== document.body
              ? active : null;
          }}
          onCloseAutoFocus={event => {
            const target = returnFocusTarget.current;
            returnFocusTarget.current = null;
            // A busy/removed launcher must never be focused after close.
            // If absent, do not override Radix's normal close behavior.
            if (target?.isConnected && !target.matches(':disabled') &&
                !target.closest('[aria-disabled="true"], [inert], [hidden]')) {
              event.preventDefault();
              target.focus();
            }
          }}
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
              onClick={() => { if (!busy) onOpenChange(false); }}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>
          <Dialog.Description asChild>
            <div className="nfc-v2-confirm-description">{description}</div>
          </Dialog.Description>
          <div className="nfc-v2-confirm-actions">
            <ConsoleButton disabled={busy} onClick={() => { if (!busy) onOpenChange(false); }}>取消</ConsoleButton>
            <ConsoleButton variant={danger ? 'danger' : 'primary'}
              disabled={busy || disabled} loading={busy}
              onClick={() => { if (!busy && !disabled) onConfirm(); }}>
              {confirmText}
            </ConsoleButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
