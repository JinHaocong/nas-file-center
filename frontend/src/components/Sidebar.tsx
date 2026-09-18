import React from 'react';
import { Layout, Menu } from 'antd';
import type { MenuProps } from 'antd';
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
interface Props {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  embedded?: boolean;
  onNavigate?: () => void;
}

const leafMenuItems: NonNullable<MenuProps['items']> = [
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

const groupLabel = (label: string) => <span className="nfc-nav-group-label">{label}</span>;

const groupedMenuItems: MenuProps['items'] = [
  {
    type: 'group',
    label: groupLabel('概览'),
    children: [leafMenuItems[0]],
  },
  {
    type: 'group',
    label: groupLabel('数据与扫描'),
    children: [leafMenuItems[1], leafMenuItems[2]],
  },
  {
    type: 'group',
    label: groupLabel('文件工具'),
    children: [leafMenuItems[3], leafMenuItems[4], leafMenuItems[5], leafMenuItems[6]],
  },
  {
    type: 'group',
    label: groupLabel('自动化'),
    children: [leafMenuItems[7]],
  },
  {
    type: 'group',
    label: groupLabel('安全与运行'),
    children: [leafMenuItems[8], leafMenuItems[9], leafMenuItems[10], leafMenuItems[11]],
  },
  {
    type: 'group',
    label: groupLabel('系统'),
    children: [leafMenuItems[12]],
  },
];

export const Sidebar: React.FC<Props> = ({
  collapsed,
  onCollapse,
  embedded = false,
  onNavigate,
}) => {
  const location = useLocation();
  const navigate = useNavigate();

  const selectedKey = '/' + location.pathname.split('/')[1];
  const menuItems = collapsed && !embedded ? leafMenuItems : groupedMenuItems;

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
            <span className="nfc-brand-title">NAS File Center</span>
            <span className="nfc-sidebar-meta">
              <span>CONTROL PLANE</span>
              <span className="nfc-sidebar-meta-separator" aria-hidden="true">/</span>
              <span>v0.4</span>
            </span>
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
      width={232}
      theme="light"
      className="nfc-sidebar"
    >
      {navigation}
    </Sider>
  );
};
