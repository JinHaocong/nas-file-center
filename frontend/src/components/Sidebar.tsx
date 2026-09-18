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
  SafetyCertificateOutlined,
  DeploymentUnitOutlined,
} from '@ant-design/icons';

const { Sider } = Layout;
const { Text } = Typography;

interface Props {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  embedded?: boolean;
  onNavigate?: () => void;
}

export const Sidebar: React.FC<Props> = ({
  collapsed,
  onCollapse,
  embedded = false,
  onNavigate,
}) => {
  const location = useLocation();
  const navigate = useNavigate();

  const menuItems = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: '系统概览' },
    { key: '/indexes', icon: <FolderOpenOutlined />, label: '文件索引' },
    { key: '/scans', icon: <ScanOutlined />, label: '扫描去重' },
    { key: '/path-match', icon: <BranchesOutlined />, label: '路径匹配' },
    { key: '/rename', icon: <EditOutlined />, label: '批量重命名' },
    { key: '/batch', icon: <AppstoreOutlined />, label: '批量处理' },
    { key: '/organizer', icon: <FolderViewOutlined />, label: 'Organizer 整理' },
    { key: '/workflows', icon: <DeploymentUnitOutlined />, label: '工作流中心' },
    { key: '/plans', icon: <ScheduleOutlined />, label: '执行计划' },
    { key: '/quarantine', icon: <SafetyCertificateOutlined />, label: '文件隔离区' },
    { key: '/tasks', icon: <ThunderboltOutlined />, label: '任务中心' },
    { key: '/audit', icon: <AuditOutlined />, label: '审计日志' },
    { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
  ];

  const selectedKey = '/' + location.pathname.split('/')[1];

  const go = (path: string) => {
    navigate(path);
    onNavigate?.();
  };

  const navigation = (
    <>
      <button
        type="button"
        className={collapsed && !embedded ? 'nfc-brand nfc-brand-collapsed' : 'nfc-brand'}
        onClick={() => go('/dashboard')}
        aria-label="返回系统概览"
      >
        <span className="nfc-brand-mark" aria-hidden="true">
          <HddOutlined />
        </span>
        {(!collapsed || embedded) && (
          <span className="nfc-brand-copy">
            <Text strong className="nfc-brand-title">
              NAS File Center
            </Text>
            <Text type="secondary" className="nfc-brand-version">
              v0.4.0 UI Preview
            </Text>
          </span>
        )}
      </button>

      <Menu
        mode="inline"
        selectedKeys={[selectedKey || '/dashboard']}
        items={menuItems}
        onClick={({ key }) => go(key)}
        className="nfc-sidebar-menu"
      />
    </>
  );

  if (embedded) {
    return <nav className="nfc-mobile-sidebar" aria-label="主导航">{navigation}</nav>;
  }

  return (
    <Sider
      collapsible
      trigger={null}
      collapsed={collapsed}
      onCollapse={onCollapse}
      width={224}
      theme="light"
      className="nfc-sidebar"
    >
      {navigation}
    </Sider>
  );
};
