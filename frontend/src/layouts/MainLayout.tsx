import React, { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Header } from '../components/Header';
import { ResponsiveNav } from '../components/layout/ResponsiveNav';
import { MobileDock } from '../components/layout/MobileDock';
import { ConsoleIcon } from '../components/ui/ConsoleIcon';
import { useResponsive } from '../hooks/useResponsive';

export const MainLayout: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  const { isMobile } = useResponsive();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  if (loading) {
    return (
      <div className="nfc-session-loading">
        <ConsoleIcon name="shield-check" size={28} />
        <span>正在验证 NAS 管理员会话...</span>
      </div>
    );
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />;

  return (
    <div className="nfc-app-shell nfc-v2-shell">
      <ResponsiveNav
        isMobile={isMobile}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
        collapsed={collapsed}
        onCollapse={setCollapsed}
      />
      <div className="nfc-app-main nfc-v2-main">
        <Header
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          isMobile={isMobile}
          onOpenNavigation={() => setMobileNavOpen(true)}
        />
        <main className="nfc-page-content nfc-v2-page-content" id="main-content">
          <Outlet />
        </main>
        {isMobile && <MobileDock onMore={() => setMobileNavOpen(true)} />}
      </div>
    </div>
  );
};
