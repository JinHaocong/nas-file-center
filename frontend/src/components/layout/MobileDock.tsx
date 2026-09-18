import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AppstoreOutlined,
  MoreOutlined,
  ScanOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';

interface MobileDockProps {
  onMore: () => void;
}

const primaryItems = [
  { key: '/dashboard', label: '概览', icon: <AppstoreOutlined /> },
  { key: '/scans', label: '扫描', icon: <ScanOutlined /> },
  { key: '/plans', label: '计划', icon: <ScheduleOutlined /> },
  { key: '/tasks', label: '任务', icon: <ThunderboltOutlined /> },
] as const;

export const MobileDock: React.FC<MobileDockProps> = ({ onMore }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedKey = '/' + location.pathname.split('/')[1];

  return (
    <nav className="nfc-mobile-dock" aria-label="移动端快捷导航">
      <div className="nfc-mobile-dock-surface">
        {primaryItems.map((item) => {
          const active = selectedKey === item.key;
          return (
            <button
              type="button"
              key={item.key}
              className={active ? 'nfc-mobile-dock-item is-active' : 'nfc-mobile-dock-item'}
              onClick={() => navigate(item.key)}
              aria-current={active ? 'page' : undefined}
            >
              <span className="nfc-mobile-dock-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          );
        })}
        <button type="button" className="nfc-mobile-dock-item" onClick={onMore}>
          <span className="nfc-mobile-dock-icon" aria-hidden="true"><MoreOutlined /></span>
          <span>更多</span>
        </button>
      </div>
    </nav>
  );
};
