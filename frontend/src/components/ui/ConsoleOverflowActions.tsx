import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { ConsoleButton } from './ConsoleButton';
import { ConsoleIcon } from './ConsoleIcon';

type Dismiss = (restoreFocus?: boolean) => void;

/** Keep secondary actions next to their primary action and support native Tab order. */
export function ConsoleOverflowActions({ children, placement = 'top' }: {
  children: (close: Dismiss) => ReactNode;
  placement?: 'top' | 'bottom';
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const contentId = useId();

  /** Close the panel, optionally returning focus for keyboard or in-place actions. */
  function close(restoreFocus = false) {
    setOpen(false);
    if (restoreFocus) trigger.current?.focus({ preventScroll: true });
  }

  useEffect(() => {
    if (!open) return;
    const onOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', onOutside);
    return () => document.removeEventListener('pointerdown', onOutside);
  }, [open]);

  return (
    <div ref={root} className="nfc-overflow-actions" data-placement={placement} data-open={open || undefined}
      onBlur={event => {
        if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) close();
      }}
      onKeyDown={event => {
        if (!open || event.key !== 'Escape') return;
        event.preventDefault();
        event.stopPropagation();
        close(true);
      }}>
      <ConsoleButton ref={trigger} size="sm" variant="secondary" className="nfc-overflow-trigger"
        aria-label="更多操作" title="更多操作" aria-expanded={open} aria-controls={open ? contentId : undefined}
        leadingIcon={<ConsoleIcon name="ellipsis" size={17} />} onClick={() => setOpen(current => !current)} />
      {open && <div id={contentId} role="group" aria-label="更多操作" className="nfc-overflow-panel">{children(close)}</div>}
    </div>
  );
}
