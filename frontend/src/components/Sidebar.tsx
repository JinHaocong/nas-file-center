import React from 'react';
import { Layout, Menu, Typography } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  DashboardOutlined,
  FolderOpenOutlined,
  ScanOutlined,
  BranchesOutlined,
  EditOutlined,
  AppstoreOutlined,
  FolderViewOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
  AuditOutlined,
  SettingOutlined,
  HddOutlined,
} from '@ant-design/icons';

const { Sider } = Layout;
const { Text } = Typography;

interface Props {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

export const Sidebar: React.FC<Props> = ({ collapsed, onCollapse }) => {
  const location = useLocation();
  const navigate = useNavigate();

  const menuItems = [
    {
      key: '/dashboard',
      icon: <DashboardOutlined />,
      label: '系统概览',
    },
    {
      key: '/indexes',
      icon: <FolderOpenOutlined />,
      label: '文件索引',
    },
    {
      key: '/scans',
      icon: <ScanOutlined />,
      label: '扫描去重',
    },
    {
      key: '/path-match',
      icon: <BranchesOutlined />,
      label: '路径匹配',
    },
    {
      key: '/rename',
      icon: <EditOutlined />,
      label: '批量重命名',
    },
    {
      key: '/batch',
      icon: <AppstoreOutlined />,
      label: '批量处理',
    },
    {
      key: '/organizer',
      icon: <FolderViewOutlined />,
      label: 'Organizer 整理',
    },
    {
      key: '/plans',
      icon: <ScheduleOutlined />,
      label: '执行计划',
    },
    {
      key: '/tasks',
      icon: <ThunderboltOutlined />,
      label: '任务中心',
    },
    {
      key: '/audit',
      icon: <AuditOutlined />,
      label: '审计日志',
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '系统设置',
    },
  ];

  // Derive selected key from pathname
  const selectedKey = '/' + location.pathname.split('/')[1];

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      width={220}
      theme="light"
      style={{
        overflow: 'auto',
        height: '100vh',
        position: 'sticky',
        top: 0,
        left: 0,
        borderRight: '1px solid rgba(0, 0, 0, 0.06)',
      }}
    >
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          padding: collapsed ? '0' : '0 20px',
          borderBottom: '1px solid rgba(0, 0, 0, 0.06)',
          cursor: 'pointer',
        }}
        onClick={() => navigate('/dashboard')}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 18,
            flexShrink: 0,
          }}
        >
          <HddOutlined />
        </div>
        {!collapsed && (
          <div style={{ marginLeft: 12, display: 'flex', flexDirection: 'column' }}>
            <Text strong style={{ fontSize: 15, lineHeight: 1.2 }}>
              NAS File Center
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              v0.3.3 Enterprise
            </Text>
          </div>
        )}
      </div>

      <Menu
        mode="inline"
        selectedKeys={[selectedKey || '/dashboard']}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        style={{ borderRight: 0, marginTop: 8 }}
      />
    </Sider>
  );
};
