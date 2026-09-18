import React from 'react';
import { Drawer } from 'antd';
import { Sidebar } from '../Sidebar';

interface ResponsiveNavProps {
  isMobile: boolean;
  mobileOpen: boolean;
  onMobileClose: () => void;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

export const ResponsiveNav: React.FC<ResponsiveNavProps> = ({
  isMobile,
  mobileOpen,
  onMobileClose,
  collapsed,
  onCollapse,
}) => {
  if (isMobile) {
    return (
      <Drawer
        placement="left"
        width={288}
        open={mobileOpen}
        onClose={onMobileClose}
        closable={false}
        className="nfc-mobile-nav-drawer"
      >
        <Sidebar
          collapsed={false}
          onCollapse={onCollapse}
          embedded
          onNavigate={onMobileClose}
        />
      </Drawer>
    );
  }

  return <Sidebar collapsed={collapsed} onCollapse={onCollapse} />;
};
