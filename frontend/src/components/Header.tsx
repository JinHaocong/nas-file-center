import React, { useState } from 'react';
import { Layout, Button, Dropdown, Space, Avatar, Typography, MenuProps } from 'antd';
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
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
}

export const Header: React.FC<Props> = ({ collapsed, onToggle }) => {
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

  return (
    <>
      <AntHeader
        style={{
          padding: '0 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: 0,
          zIndex: 10,
          borderBottom: '1px solid rgba(0, 0, 0, 0.06)',
        }}
      >
        <Space size="middle">
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={onToggle}
            style={{ fontSize: 16 }}
          />
          <SafeModeBadge />
          <WorkerStatusBadge />
        </Space>

        <Space size="middle">
          <Dropdown menu={{ items: themeMenuItems, selectedKeys: [mode] }} trigger={['click']}>
            <Button type="text" icon={mode === 'dark' ? <MoonOutlined /> : mode === 'light' ? <SunOutlined /> : <DesktopOutlined />}>
              <span style={{ marginLeft: 4, textTransform: 'capitalize' }}>{mode}</span>
            </Button>
          </Dropdown>

          <Dropdown menu={{ items: userMenuItems }} trigger={['click']}>
            <Button type="text" style={{ padding: '0 8px', height: 40 }}>
              <Space>
                <Avatar size="small" icon={<UserOutlined />} style={{ backgroundColor: '#1677ff' }} />
                <Text strong>{user?.username || 'Admin'}</Text>
              </Space>
            </Button>
          </Dropdown>
        </Space>
      </AntHeader>

      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
    </>
  );
};
