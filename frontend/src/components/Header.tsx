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
import { useLocation } from 'react-router-dom';
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

interface WorkspaceContext {
  kicker: string;
  name: string;
}

const resolveWorkspaceContext = (pathname: string): WorkspaceContext => {
  if (pathname.startsWith('/scans/')) {
    return pathname.endsWith('/dedupe')
      ? { kicker: 'DATA & SCAN', name: '高级去重工作台' }
      : { kicker: 'DATA & SCAN', name: '扫描详情' };
  }

  if (pathname.startsWith('/plans/')) return { kicker: 'SAFETY & RUN', name: '执行计划详情' };
  if (pathname.startsWith('/workflows/')) return { kicker: 'AUTOMATION', name: '工作流编辑器' };

  const root = '/' + pathname.split('/').filter(Boolean)[0];
  const contexts: Record<string, WorkspaceContext> = {
    '/dashboard': { kicker: 'OVERVIEW', name: '系统概览' },
    '/indexes': { kicker: 'DATA & SCAN', name: '文件索引' },
    '/scans': { kicker: 'DATA & SCAN', name: '扫描去重' },
    '/path-match': { kicker: 'FILE TOOLS', name: '路径匹配' },
    '/rename': { kicker: 'FILE TOOLS', name: '批量重命名' },
    '/batch': { kicker: 'FILE TOOLS', name: '批量处理' },
    '/organizer': { kicker: 'FILE TOOLS', name: 'Organizer 整理' },
    '/workflows': { kicker: 'AUTOMATION', name: '工作流中心' },
    '/plans': { kicker: 'SAFETY & RUN', name: '执行计划' },
    '/quarantine': { kicker: 'SAFETY & RUN', name: '文件隔离区' },
    '/tasks': { kicker: 'SAFETY & RUN', name: '任务中心' },
    '/audit': { kicker: 'SAFETY & RUN', name: '审计日志' },
    '/settings': { kicker: 'SYSTEM', name: '系统设置' },
  };

  return contexts[root] || { kicker: 'CONTROL PLANE', name: 'NAS File Center' };
};

export const Header: React.FC<Props> = ({
  collapsed,
  onToggle,
  isMobile = false,
  onOpenNavigation,
}) => {
  const { user, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const location = useLocation();
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const workspace = resolveWorkspaceContext(location.pathname);

  const themeMenuItems: MenuProps['items'] = [
    { key: 'light', icon: <SunOutlined />, label: '浅色模式 (Light)', onClick: () => setMode('light') },
    { key: 'dark', icon: <MoonOutlined />, label: '深色模式 (Dark)', onClick: () => setMode('dark') },
    { key: 'system', icon: <DesktopOutlined />, label: '跟随系统 (System)', onClick: () => setMode('system') },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'info',
      disabled: true,
      label: (
        <div className="nfc-user-menu-summary">
          <Text strong>{user?.username}</Text>
          <span className="nfc-user-menu-role">角色: {user?.role || '管理员'}</span>
        </div>
      ),
    },
    { type: 'divider' },
    { key: 'password', icon: <KeyOutlined />, label: '修改密码', onClick: () => setPasswordModalOpen(true) },
    { key: 'logout', icon: <LogoutOutlined />, danger: true, label: '退出登录', onClick: () => logout() },
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
            className="nfc-touch-button nfc-header-nav-toggle"
            aria-label={isMobile ? '打开导航菜单' : collapsed ? '展开侧边导航' : '收起侧边导航'}
            icon={isMobile ? <MenuOutlined /> : collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={handleNavigationToggle}
          />

          <div className="nfc-header-workspace" aria-label="当前工作区">
            <span className="nfc-header-workspace-kicker">{workspace.kicker}</span>
            <span className="nfc-header-workspace-name">{workspace.name}</span>
          </div>

          <div className="nfc-header-status" aria-label="系统安全与任务状态">
            <SafeModeBadge />
            <WorkerStatusBadge />
          </div>
        </div>

        <div className="nfc-header-command-cluster">
          <Dropdown menu={{ items: themeMenuItems, selectedKeys: [mode] }} trigger={['click']}>
            <Button
              type="text"
              className="nfc-touch-button nfc-command-button"
              aria-label="切换界面主题"
              icon={mode === 'dark' ? <MoonOutlined /> : mode === 'light' ? <SunOutlined /> : <DesktopOutlined />}
            >
              {!isMobile && <span className="nfc-header-action-label">{mode}</span>}
            </Button>
          </Dropdown>

          <Dropdown menu={{ items: userMenuItems }} trigger={['click']}>
            <Button type="text" className="nfc-touch-button nfc-command-button" aria-label="打开管理员菜单">
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
