import React, { useState } from 'react';
import { Layout, Button, Dropdown, Space, Avatar, Typography, MenuProps } from 'antd';
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MenuOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  SunOutlined,
  MoonOutlined,
  DesktopOutlined,
} from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { SafeModeBadge } from './SafeModeBadge';
import { WorkerStatusBadge } from './WorkerStatusBadge';
import { ChangePasswordModal } from './ChangePasswordModal';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  isMobile?: boolean;
  onOpenNavigation?: () => void;
}

export const Header: React.FC<Props> = ({
  collapsed,
  onToggle,
  isMobile = false,
  onOpenNavigation,
}) => {
  const { user, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);

  const themeMenuItems: MenuProps['items'] = [
    {
      key: 'light',
      icon: <SunOutlined />,
      label: '浅色模式 (Light)',
      onClick: () => setMode('light'),
    },
    {
      key: 'dark',
      icon: <MoonOutlined />,
      label: '深色模式 (Dark)',
      onClick: () => setMode('dark'),
    },
    {
      key: 'system',
      icon: <DesktopOutlined />,
      label: '跟随系统 (System)',
      onClick: () => setMode('system'),
    },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'info',
      disabled: true,
      label: (
        <div style={{ padding: '4px 0' }}>
          <Text strong>{user?.username}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            角色: {user?.role || '管理员'}
          </Text>
        </div>
      ),
    },
    { type: 'divider' },
    {
      key: 'password',
      icon: <KeyOutlined />,
      label: '修改密码',
      onClick: () => setPasswordModalOpen(true),
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      danger: true,
      label: '退出登录',
      onClick: () => logout(),
    },
  ];

  const handleNavigationToggle = () => {
    if (isMobile) {
      onOpenNavigation?.();
      return;
    }
    onToggle();
  };

  return (
    <>
      <AntHeader className="nfc-header">
        <div className="nfc-header-left">
          <Button
            type="text"
            className="nfc-touch-button"
            aria-label={isMobile ? '打开导航菜单' : collapsed ? '展开侧边导航' : '收起侧边导航'}
            icon={
              isMobile ? (
                <MenuOutlined />
              ) : collapsed ? (
                <MenuUnfoldOutlined />
              ) : (
                <MenuFoldOutlined />
              )
            }
            onClick={handleNavigationToggle}
          />

          <div className="nfc-header-status" aria-label="系统安全与任务状态">
            <SafeModeBadge />
            <WorkerStatusBadge />
          </div>
        </div>

        <div className="nfc-header-actions">
          <Dropdown menu={{ items: themeMenuItems, selectedKeys: [mode] }} trigger={['click']}>
            <Button
              type="text"
              className="nfc-touch-button"
              aria-label="切换界面主题"
              icon={mode === 'dark' ? <MoonOutlined /> : mode === 'light' ? <SunOutlined /> : <DesktopOutlined />}
            >
              {!isMobile && <span className="nfc-header-action-label">{mode}</span>}
            </Button>
          </Dropdown>

          <Dropdown menu={{ items: userMenuItems }} trigger={['click']}>
            <Button type="text" className="nfc-touch-button" aria-label="打开管理员菜单">
              <Space size={8}>
                <Avatar size="small" icon={<UserOutlined />} className="nfc-user-avatar" />
                {!isMobile && <Text strong>{user?.username || 'Admin'}</Text>}
              </Space>
            </Button>
          </Dropdown>
        </div>
      </AntHeader>

      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
    </>
  );
};
