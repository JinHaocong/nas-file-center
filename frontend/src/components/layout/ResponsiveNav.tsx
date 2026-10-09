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

  useEffect(() => {
    if (!isMobile || !mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onMobileClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKey);
    };
  }, [isMobile, mobileOpen, onMobileClose]);

  if (!isMobile) return <Sidebar collapsed={collapsed} onCollapse={onCollapse} />;
  if (!mobileOpen) return null;

  return (
    <div className="nfc-v2-mobile-nav-layer">
      <button className="nfc-v2-mobile-nav-backdrop" type="button"
        onClick={onMobileClose} aria-label="关闭导航菜单" />
      <div className="nfc-v2-mobile-nav-dialog" role="dialog" aria-modal="true"
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
