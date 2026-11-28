import React, { useEffect, useRef, useState } from 'react';
import { Outlet, Navigate, matchPath, useLocation } from 'react-router-dom';

import { useAuth } from '../contexts/AuthContext';
import { useWorkspaceMotion } from '../hooks/useWorkspaceMotion';
import { useWorkspaceScroll } from '../hooks/useWorkspaceScroll';
import { Header } from '../components/Header';
import { ResponsiveNav } from '../components/layout/ResponsiveNav';
import { MobileDock } from '../components/layout/MobileDock';
import { WorkspaceNavigation } from '../components/layout/WorkspaceNavigation';
import { currentDestination } from '../components/layout/navItems';
import { ConsoleIcon } from '../components/ui/ConsoleIcon';
import { useResponsive } from '../hooks/useResponsive';

const navigationCompactKey = 'nfc_navigation_compact';

/** With no saved preference, keep the existing navigation width for each workspace. */
function readNavigationCompact(): boolean | undefined {
  try {
    const saved = window.localStorage.getItem(navigationCompactKey);
    if (saved === 'true' || saved === 'false') return saved === 'true';
  } catch {
    // The desktop control still works when browser storage is unavailable.
  }
  return undefined;
}

/** Mount the workspace and preserve the actual opener across menu navigation. */
export const MainLayout: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  const { isMobile, isDesktop } = useResponsive();
  const { pathname, search } = useLocation();
  const fileSpace = Boolean(matchPath('/dashboard', pathname)) && new URLSearchParams(search).get('view') !== 'overview';
  const [preferredCompact, setPreferredCompact] = useState(readNavigationCompact);
  const compactNavigation = preferredCompact ?? (
    fileSpace || currentDestination(pathname, search) === '/batch?operation=media-organize'
  );
  const [navigationOpen, setNavigationOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);

  const main = useRef<HTMLElement>(null);
  useWorkspaceScroll(main, isAuthenticated && !loading);
  useWorkspaceMotion(main, pathname, isAuthenticated && !loading);

  useEffect(() => {
    if (!isAuthenticated || loading) return;
    /** Open tool search from anywhere in the workspace, outside active task dialogs. */
    function shortcut(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat || event.isComposing || event.altKey ||
          !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return;
      if (navigationOpen) {
        event.preventDefault();
        setNavigationOpen(false);
        return;
      }
      if (document.querySelector('[role="dialog"], [role="alertdialog"], dialog[open]')) return;
      event.preventDefault();
      opener.current = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
        ? document.activeElement : document.querySelector<HTMLButtonElement>('.nfc-header-nav-toggle');
      setNavigationOpen(true);
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [isAuthenticated, loading, navigationOpen]);

  /** Keep focus restoration bound to the exact trigger, including the phone dock. */
  function openNavigation(event: React.MouseEvent<HTMLButtonElement>) {
    opener.current = event.currentTarget;
    setNavigationOpen(true);
  }

  /** Apply the user's choice across this workspace, including after reload when supported. */
  function toggleNavigationCompact() {
    const next = !compactNavigation;
    setPreferredCompact(next);
    try {
      window.localStorage.setItem(navigationCompactKey, String(next));
    } catch {
      // Keep the in-memory choice for the current session.
    }
  }

  if (loading) {
    return <div className="nfc-session-loading" role="status">
      <ConsoleIcon name="shield-check" size={28} /><span>正在验证登录状态…</span>
    </div>;
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />;

  return <div className={'nfc-app-shell nfc-v2-shell nfc-studio' + (fileSpace ? ' nfc-file-space-shell' : '')}>
    <a className="nfc-v2-skip-link" href="#main-content">跳转到主要内容</a>
    <div className="nfc-app-main nfc-v2-main">
      <Header isMobile={isMobile} navigationOpen={navigationOpen} onOpenNavigation={openNavigation} />
      <div className="nfc-workspace-frame">
        {isDesktop && <WorkspaceNavigation compact={compactNavigation} onToggleCompact={toggleNavigationCompact} />}
        <main ref={main} className="nfc-page-content nfc-v2-page-content" id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      {isMobile && <MobileDock moreOpen={navigationOpen} onMore={openNavigation} />}
    </div>
    <ResponsiveNav open={navigationOpen} onClose={() => setNavigationOpen(false)} opener={opener} />
  </div>;
};
