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
}) => (
  <Dialog.Root open={open} onOpenChange={next => { if (!next) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="nfc-v2-dialog-overlay" />
      <Dialog.Content className={'nfc-v2-sheet nfc-overlay-drawer ' + className}>
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
