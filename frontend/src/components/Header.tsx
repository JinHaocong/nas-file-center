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

const routeLabels: Record<string, string> = {
  dashboard: '系统概览',
  indexes: '文件索引',
  scans: '扫描去重',
  media: '媒体完整性',
  'path-match': '路径匹配',
  rename: '批量重命名',
  batch: '批量处理',
  organizer: '目录整理',
  workflows: '工作流中心',
  schedules: '计划任务',
  plans: '执行计划',
  tasks: '任务中心',
  quarantine: '文件隔离区',
  audit: '审计日志',
  settings: '系统设置',
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
  const routeKey = location.pathname.split('/')[1] || 'dashboard';
  const currentArea = routeLabels[routeKey] || 'NAS File Center';

  const themeMenuItems: MenuProps['items'] = [
    { key: 'light', icon: <SunOutlined />, label: '浅色模式', onClick: () => setMode('light') },
    { key: 'dark', icon: <MoonOutlined />, label: '深色模式', onClick: () => setMode('dark') },
    { key: 'system', icon: <DesktopOutlined />, label: '跟随系统', onClick: () => setMode('system') },
  ];

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'info',
      disabled: true,
      label: (
        <div className="nfc-user-menu-summary">
          <Text strong>{user?.username}</Text>
          <span className="nfc-user-menu-role">角色：{user?.role || '管理员'}</span>
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
          <div className="nfc-header-location" aria-label="当前位置">
            <span className="nfc-header-location-label">当前位置</span>
            <strong>{currentArea}</strong>
          </div>
        </div>

        <div className="nfc-header-command-cluster">
          {!isMobile && (
            <div className="nfc-header-status" aria-label="系统安全与任务状态">
              <SafeModeBadge />
              <WorkerStatusBadge />
            </div>
          )}

          <Dropdown menu={{ items: themeMenuItems, selectedKeys: [mode] }} trigger={['click']}>
            <Button
              type="text"
              className="nfc-touch-button nfc-command-button"
              aria-label="切换界面主题"
              icon={mode === 'dark' ? <MoonOutlined /> : mode === 'light' ? <SunOutlined /> : <DesktopOutlined />}
            />
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

      {isMobile && (
        <div className="nfc-mobile-system-strip" aria-label="系统安全与任务状态">
          <SafeModeBadge />
          <WorkerStatusBadge />
        </div>
      )}

      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
    </>
  );
};
