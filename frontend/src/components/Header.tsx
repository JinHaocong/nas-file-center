import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { SafeModeBadge } from './SafeModeBadge';
import { WorkerStatusBadge } from './WorkerStatusBadge';
import { ChangePasswordModal } from './ChangePasswordModal';
import { ConsoleIcon } from './ui/ConsoleIcon';
import { navLabel } from './layout/navItems';

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  isMobile?: boolean;
  onOpenNavigation?: () => void;
}

export const Header: React.FC<Props> = ({
  collapsed, onToggle, isMobile = false, onOpenNavigation,
}) => {
  const { user, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const location = useLocation();
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);

  const toggleNav = () => isMobile ? onOpenNavigation?.() : onToggle();
  return (
    <>
      <header className="nfc-header nfc-v2-header">
        <div className="nfc-header-left nfc-v2-header-left">
          <button type="button" className="nfc-v2-icon-button nfc-header-nav-toggle"
            onClick={toggleNav}
            aria-label={isMobile ? '打开导航菜单' : collapsed ? '展开侧边导航' : '收起侧边导航'}>
            <ConsoleIcon name="menu" size={20} />
          </button>
          <div className="nfc-v2-breadcrumb">
            <span>工作台</span><ConsoleIcon name="chevron-right" size={14} />
            <strong>{navLabel(location.pathname)}</strong>
          </div>
        </div>
        <div className="nfc-header-command-cluster">
          <div className="nfc-header-status" aria-label="系统安全与任务状态">
            <SafeModeBadge />
            <WorkerStatusBadge />
          </div>
          <div className="nfc-v2-header-divider" aria-hidden="true" />
          <details className="nfc-v2-dropdown">
            <summary className="nfc-v2-icon-button" aria-label="切换界面主题" title="切换主题">
              <ConsoleIcon name={mode === 'dark' ? 'moon' : 'sun'} size={19} />
            </summary>
            <div className="nfc-v2-menu">
              {([
                ['light', '浅色模式', 'sun'],
                ['dark', '深色模式', 'moon'],
                ['system', '跟随系统', 'settings'],
              ] as const).map(([key, label, icon]) => (
                <button type="button" key={key}
                  aria-pressed={mode === key}
                  onClick={event => {
                    setMode(key);
                    event.currentTarget.closest('details')?.removeAttribute('open');
                  }}>
                  <ConsoleIcon name={icon} size={16} />{label}
                  {mode === key && <ConsoleIcon className="nfc-v2-selected-check" name="check" size={15} />}
                </button>
              ))}
            </div>
          </details>
          <details className="nfc-v2-dropdown nfc-v2-user-dropdown">
            <summary className="nfc-v2-user-button" aria-label="打开管理员菜单">
              <span className="nfc-v2-avatar"><ConsoleIcon name="user" size={18} /></span>
              {!isMobile && <strong>{user?.username || 'Admin'}</strong>}
              <ConsoleIcon name="chevron-down" size={14} />
            </summary>
            <div className="nfc-v2-menu">
              <div className="nfc-v2-menu-identity">
                <strong>{user?.username || 'Admin'}</strong>
                <span>角色：{user?.role || '管理员'}</span>
              </div>
              <button type="button" onClick={event => {
                setPasswordModalOpen(true);
                event.currentTarget.closest('details')?.removeAttribute('open');
              }}><ConsoleIcon name="lock" size={16} /> 修改密码</button>
              <button type="button" className="nfc-v2-menu-danger" onClick={() => logout()}>
                <ConsoleIcon name="log-out" size={16} /> 退出登录
              </button>
            </div>
          </details>
        </div>
      </header>
      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
    </>
  );
};
