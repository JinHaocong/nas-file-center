import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import type { ConsoleIconName } from '../ui/ConsoleIcon';

interface Props { onMore: () => void }

const primaryItems: Array<{ key: string; label: string; icon: ConsoleIconName }> = [
  { key: '/dashboard', label: '概览', icon: 'layout-dashboard' },
  { key: '/scans', label: '扫描', icon: 'layers' },
  { key: '/plans', label: '计划', icon: 'list-checks' },
  { key: '/tasks', label: '任务', icon: 'activity' },
];

export const MobileDock: React.FC<Props> = ({ onMore }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const activeRoot = '/' + location.pathname.split('/')[1];

  return (
    <nav className="nfc-mobile-dock nfc-v2-mobile-dock" aria-label="移动端快捷导航">
      <div className="nfc-mobile-dock-surface">
        {primaryItems.map(item => (
          <button type="button" key={item.key}
            className={'nfc-mobile-dock-item' + (activeRoot === item.key ? ' is-active' : '')}
            aria-current={activeRoot === item.key ? 'page' : undefined}
            onClick={() => navigate(item.key)}>
            <ConsoleIcon name={item.icon} size={20} />
            <span>{item.label}</span>
          </button>
        ))}
        <button type="button" className="nfc-mobile-dock-item" onClick={onMore}>
          <ConsoleIcon name="menu" size={20} /><span>更多</span>
        </button>
      </div>
    </nav>
  );
};
