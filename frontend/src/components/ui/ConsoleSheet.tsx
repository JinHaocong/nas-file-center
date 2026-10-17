import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ConsoleIcon } from './ConsoleIcon';

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
  eyebrow?: string;
  titleAside?: React.ReactNode;
}

/** Right-aligned Radix sheet with controlled close and accessible focus behavior. */
export const ConsoleSheet: React.FC<Props> = ({
  open, onClose, title, description, children, className = '',
  eyebrow = 'INSPECTOR', titleAside,
}) => {
  // Controlled Sheets have no Dialog.Trigger, so remember the active launcher
  // before the portal moves keyboard focus into the inspector.
  const returnFocusTarget = React.useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-sheet-overlay" />
        <Dialog.Content
          className={'nfc-v2-sheet nfc-overlay-drawer ' + className}
          onOpenAutoFocus={() => {
            const active = document.activeElement;
            returnFocusTarget.current = active instanceof HTMLElement && active !== document.body
              ? active : null;
          }}
          onCloseAutoFocus={event => {
            const target = returnFocusTarget.current;
            returnFocusTarget.current = null;
            // Lists can refresh or remove the opener; never focus detached or
            // disabled elements. Fall back to Radix's normal close semantics.
            if (target?.isConnected && !target.matches(':disabled') &&
                !target.closest('[aria-disabled="true"], [inert], [hidden]')) {
              event.preventDefault();
              target.focus();
            }
          }}
        >
          <header className="nfc-v2-sheet-header">
            <div className="nfc-v2-sheet-heading">
              <span className="nfc-v2-sheet-eyebrow">{eyebrow}</span>
              <div className="nfc-v2-sheet-title-row">
                <Dialog.Title>{title}</Dialog.Title>
                {titleAside}
              </div>
              <Dialog.Description className="nfc-v2-sheet-description">
                {description}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button type="button" className="nfc-v2-dialog-close"
                aria-label="关闭详情抽屉">
                <ConsoleIcon name="x" size={20} />
              </button>
            </Dialog.Close>
          </header>
          <div className="nfc-v2-sheet-body">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
