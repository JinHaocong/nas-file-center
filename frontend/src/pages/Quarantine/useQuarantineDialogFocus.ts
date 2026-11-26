import { useRef } from 'react';

/** Return to the original selection control when a controlled quarantine dialog closes. */
export function useQuarantineDialogFocus() {
  const opener = useRef<HTMLElement | null>(null);

  return {
    onOpenAutoFocus() {
      const active = document.activeElement;
      opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
    },
    onCloseAutoFocus(event: Event) {
      const active = opener.current;
      opener.current = null;
      if (!active?.isConnected || active.matches(':disabled') || active.closest('[hidden], [inert]')) return;
      event.preventDefault();
      active.focus({ preventScroll: true });
    },
  };
}
