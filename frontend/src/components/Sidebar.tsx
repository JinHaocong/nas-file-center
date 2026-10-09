import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ConsoleIcon } from './ui/ConsoleIcon';
import { consoleNavGroups } from './layout/navItems';

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
  const compact = collapsed && !embedded;
  const selectedKey = '/' + location.pathname.split('/')[1];
  const go = (path: string) => {
    navigate(path);
    onNavigate?.();
  };

  const navigation = (
    <>
      <button
        type="button"
        className="nfc-v2-brand"
        onClick={() => go('/dashboard')}
        title={compact ? 'NAS File Center — 返回仪表盘' : undefined}
        aria-label="NAS File Center — 返回仪表盘"
      >
        <span className="nfc-v2-brand-icon"><ConsoleIcon name="hard-drive" size={22} /></span>
        {!compact && (
          <span className="nfc-v2-brand-copy">
            <strong>NAS File Center</strong>
            <span>SECURE FILE OPERATIONS</span>
          </span>
        )}
      </button>

      <nav className="nfc-v2-nav" aria-label="主导航">
        {consoleNavGroups.map(group => (
          <section className="nfc-v2-nav-group" key={group.label} aria-label={group.label}>
            {!compact && <h2 className="nfc-v2-nav-group-title">{group.label}</h2>}
            {group.items.map(item => (
              <button
                type="button"
                key={item.path}
                title={compact ? item.label : undefined}
                aria-label={item.label}
                aria-current={selectedKey === item.path ? 'page' : undefined}
                className={'nfc-v2-nav-item' + (selectedKey === item.path ? ' is-active' : '')}
                onClick={() => go(item.path)}
              >
                <ConsoleIcon name={item.icon} size={19} />
                {!compact && <span>{item.label}</span>}
                {!compact && selectedKey === item.path &&
                  <ConsoleIcon className="nfc-v2-nav-current" name="chevron-right" size={15} />}
              </button>
            ))}
          </section>
        ))}
      </nav>
      <div className="nfc-v2-sidebar-footer">
        <span className="nfc-v2-sidebar-footer-icon"><ConsoleIcon name="shield-check" size={17} /></span>
        {!compact && (
          <span><strong>安全操作优先</strong><small>Preview → Plan → Execute</small></span>
        )}
      </div>
      {!embedded && (
        <button
          className="nfc-v2-sidebar-collapse"
          type="button"
          aria-label={compact ? '展开侧边栏' : '收起侧边栏'}
          title={compact ? '展开侧边栏' : '收起侧边栏'}
          onClick={() => onCollapse(!collapsed)}
        >
          <ConsoleIcon name={compact ? 'chevron-right' : 'chevron-down'} size={16} />
        </button>
      )}
    </>
  );

  if (embedded) return <div className="nfc-v2-sidebar nfc-v2-sidebar-mobile">{navigation}</div>;
  return (
    <aside className={'nfc-v2-sidebar' + (compact ? ' is-collapsed' : '')}>
      {navigation}
    </aside>
  );
};
