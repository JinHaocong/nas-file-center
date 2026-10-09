import React, { useEffect, useRef } from 'react';
import { Sidebar } from '../Sidebar';
import { ConsoleIcon } from '../ui/ConsoleIcon';

interface ResponsiveNavProps {
  isMobile: boolean;
  mobileOpen: boolean;
  onMobileClose: () => void;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

export const ResponsiveNav: React.FC<ResponsiveNavProps> = ({
  isMobile, mobileOpen, onMobileClose, collapsed, onCollapse,
}) => {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isMobile || !mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onMobileClose();
      } else if (event.key === 'Tab') {
        const buttons = dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        );
        if (!buttons?.length) return;
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKey);
      previouslyFocused?.focus();
    };
  }, [isMobile, mobileOpen, onMobileClose]);

  if (!isMobile) return <Sidebar collapsed={collapsed} onCollapse={onCollapse} />;
  if (!mobileOpen) return null;

  return (
    <div className="nfc-v2-mobile-nav-layer">
      <button className="nfc-v2-mobile-nav-backdrop" type="button"
        onClick={onMobileClose} aria-label="关闭导航菜单" />
      <div ref={dialogRef} className="nfc-v2-mobile-nav-dialog" role="dialog" aria-modal="true"
        aria-label="NAS File Center 主导航">
        <button ref={closeRef} type="button" className="nfc-v2-mobile-nav-close"
          aria-label="关闭导航菜单" onClick={onMobileClose}>
          <ConsoleIcon name="x" size={20} />
        </button>
        <Sidebar collapsed={false} onCollapse={onCollapse} embedded onNavigate={onMobileClose} />
      </div>
    </div>
  );
};
