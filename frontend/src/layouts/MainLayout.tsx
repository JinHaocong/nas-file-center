import React, { useState } from 'react';
import { Layout, Spin } from 'antd';
import { Outlet, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Header } from '../components/Header';
import { ResponsiveNav } from '../components/layout/ResponsiveNav';
import { useResponsive } from '../hooks/useResponsive';

const { Content } = Layout;

export const MainLayout: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  const { isMobile } = useResponsive();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  if (loading) {
    return (
      <div className="nfc-session-loading">
        <Spin size="large" />
        <span>正在验证 NAS 管理员会话...</span>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <Layout className="nfc-app-shell">
      <ResponsiveNav
        isMobile={isMobile}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
        collapsed={collapsed}
        onCollapse={setCollapsed}
      />
      <Layout className="nfc-app-main">
        <Header
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          isMobile={isMobile}
          onOpenNavigation={() => setMobileNavOpen(true)}
        />
        <Content className="nfc-page-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
};
