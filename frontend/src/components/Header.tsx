import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { SafeModeBadge } from './SafeModeBadge';
import { WorkerStatusBadge } from './WorkerStatusBadge';
import { ChangePasswordModal } from './ChangePasswordModal';
import { ConsoleIcon } from './ui/ConsoleIcon';
import { navLabel } from './layout/navItems';

interface Props {
  isMobile: boolean;
  navigationOpen: boolean;
  onOpenNavigation: React.MouseEventHandler<HTMLButtonElement>;
  fileToolbarRef?: React.Ref<HTMLDivElement>;
}

/** Close a native disclosure and return keyboard focus to its visible trigger. */
function dismissMenu(menu: HTMLDetailsElement | null, restoreFocus = false) {
  if (!menu?.open) return;
  menu.open = false;
  if (restoreFocus) menu.querySelector('summary')?.focus();
}

/** Keep location, search, session controls and live safety indicators in the top row. */
export const Header: React.FC<Props> = ({ isMobile, navigationOpen, onOpenNavigation, fileToolbarRef }) => {
  const { user, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const location = useLocation();
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const header = useRef<HTMLElement>(null);

  useEffect(() => {
    if (navigationOpen) header.current?.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(menu => dismissMenu(menu));
  }, [navigationOpen]);

  useEffect(() => {
    const menus = header.current?.querySelectorAll('details');
    const pointer = (event: PointerEvent) => menus?.forEach(menu => {
      if (event.target instanceof Node && !menu.contains(event.target)) dismissMenu(menu);
    });
    const disclosure = (event: Event) => {
      if (event.target instanceof HTMLDetailsElement && event.target.open) {
        menus?.forEach(menu => { if (menu !== event.target) dismissMenu(menu); });
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && header.current?.contains(document.activeElement)) {
        menus?.forEach(menu => dismissMenu(menu, true));
      }
    };
    menus?.forEach(menu => menu.addEventListener('toggle', disclosure));
    document.addEventListener('pointerdown', pointer);
    document.addEventListener('keydown', escape);
    return () => {
      menus?.forEach(menu => menu.removeEventListener('toggle', disclosure));
      document.removeEventListener('pointerdown', pointer);
      document.removeEventListener('keydown', escape);
    };
  }, []);

  return <>
    <header className={'nfc-header nfc-v2-header' + (fileToolbarRef ? ' has-file-toolbar' : '')} ref={header}>
      <div className="nfc-header-left nfc-v2-header-left">
        <Link className="nfc-studio-brand" to="/dashboard" aria-label="NAS File Center 文件空间">
          <span className="nfc-studio-mark"><ConsoleIcon name="hard-drive" size={18} /></span>
          <strong>NAS File Center</strong>
        </Link>
        {!fileToolbarRef && <div className="nfc-v2-breadcrumb">
          <ConsoleIcon name="chevron-right" size={13} />
          <strong>{navLabel(location.pathname, location.search)}</strong>
        </div>}
      </div>
      {fileToolbarRef && <div className="nfc-header-file-toolbar" ref={fileToolbarRef} />}
      <div className="nfc-header-command-cluster">
        <div className="nfc-header-status" aria-label="系统安全与任务状态">
          <SafeModeBadge /><WorkerStatusBadge />
        </div>
        <button type="button" className="nfc-v2-icon-button nfc-header-nav-toggle" onClick={onOpenNavigation}
          aria-label="打开导航菜单" aria-haspopup="dialog" aria-expanded={navigationOpen} aria-keyshortcuts="Control+K Meta+K" title="所有工具">
          <ConsoleIcon name={fileToolbarRef ? 'menu' : 'search'} size={16} /><span>查找工具</span><kbd aria-hidden="true">{typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K'}</kbd>
        </button>
        <details className="nfc-v2-dropdown">
          <summary className="nfc-v2-icon-button" aria-label="切换界面主题" title="切换主题">
            <ConsoleIcon name={mode === 'dark' ? 'moon' : 'sun'} size={17} />
          </summary>
          <div className="nfc-v2-menu">
            {([['light', '浅色模式', 'sun'], ['dark', '深色模式', 'moon'],
              ['system', '跟随系统', 'settings']] as const).map(([key, label, icon]) =>
              <button type="button" key={key} aria-pressed={mode === key} onClick={event => {
                setMode(key);
                dismissMenu(event.currentTarget.closest('details'), true);
              }}>
                <ConsoleIcon name={icon} size={16} />{label}
                {mode === key && <ConsoleIcon className="nfc-v2-selected-check" name="check" size={15} />}
              </button>)}
          </div>
        </details>
        <details className="nfc-v2-dropdown nfc-v2-user-dropdown">
          <summary className="nfc-v2-user-button" aria-label="打开管理员菜单">
            <span className="nfc-v2-avatar"><ConsoleIcon name="user" size={17} /></span>
            {!isMobile && <strong>{user?.username || 'Admin'}</strong>}
            <ConsoleIcon name="chevron-down" size={13} />
          </summary>
          <div className="nfc-v2-menu">
            <div className="nfc-v2-menu-identity"><strong>{user?.username || 'Admin'}</strong>
              <span>{user?.role || '管理员'}</span></div>
            <Link to="/settings" onClick={event => dismissMenu(event.currentTarget.closest('details'))}>
              <ConsoleIcon name="settings" size={16} />系统设置</Link>
            <button type="button" onClick={event => {
              dismissMenu(event.currentTarget.closest('details'), true);
              setPasswordModalOpen(true);
            }}><ConsoleIcon name="lock" size={16} /> 修改密码</button>
            <button type="button" className="nfc-v2-menu-danger" onClick={() => logout()}>
              <ConsoleIcon name="log-out" size={16} /> 退出登录</button>
          </div>
        </details>
      </div>
    </header>
    <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
  </>;
};
