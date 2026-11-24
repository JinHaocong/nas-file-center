import React, { useRef } from 'react';
import { useLocation } from 'react-router-dom';
import * as Dialog from '@radix-ui/react-dialog';
import { Sidebar } from '../Sidebar';
import { ConsoleIcon } from '../ui/ConsoleIcon';

interface Props {
  open: boolean;
  onClose: () => void;
  opener: React.RefObject<HTMLElement>;
}

/** One keyboard-accessible tool directory, centered on desktop and docked on mobile. */
export const ResponsiveNav: React.FC<Props> = ({ open, onClose, opener }) => {
  const content = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const openedAt = useRef('');
  return <Dialog.Root open={open} onOpenChange={next => { if (!next) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="nfc-v2-mobile-nav-backdrop nfc-studio-nav-backdrop" />
      <Dialog.Content ref={content} className="nfc-v2-mobile-nav-dialog nfc-studio-tools-dialog"
        aria-describedby={undefined}
        onOpenAutoFocus={event => {
          openedAt.current = location.pathname + location.search;
          const field = content.current?.querySelector('input');
          if (field && window.matchMedia?.('(min-width: 768px)').matches) {
            event.preventDefault();
            field.focus();
          }
        }}
        onCloseAutoFocus={event => {
          if (openedAt.current !== location.pathname + location.search) {
            event.preventDefault();
            document.getElementById('main-content')?.focus({ preventScroll: true });
            return;
          }
          if (opener.current?.isConnected && opener.current.getClientRects().length) {
            event.preventDefault();
            opener.current.focus();
          } else {
            event.preventDefault();
            document.querySelector<HTMLButtonElement>('.nfc-header-nav-toggle')?.focus();
          }
        }}>
        <header className="nfc-studio-tools-title">
          <Dialog.Title>所有工具</Dialog.Title>
          <Dialog.Close className="nfc-v2-mobile-nav-close" aria-label="关闭导航菜单">
            <ConsoleIcon name="x" size={19} />
          </Dialog.Close>
        </header>
        <Sidebar onNavigate={onClose} />
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
};
