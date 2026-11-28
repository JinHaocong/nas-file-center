import React, { useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ConsoleIcon } from './ui/ConsoleIcon';
import { consoleNavGroups, currentDestination } from './layout/navItems';
import { useTheme } from '../contexts/ThemeContext';

/** Search the complete tool directory, including less frequently used workflows. */
export const Sidebar: React.FC<{ onNavigate: () => void }> = ({ onNavigate }) => {
  const location = useLocation();
  const { mode, setMode } = useTheme();
  const [query, setQuery] = useState('');
  const list = useRef<HTMLElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const term = query.trim().toLocaleLowerCase();
  const selectedKey = currentDestination(location.pathname, location.search);
  const groups = consoleNavGroups.map(group => ({
    ...group, items: group.items.filter(item =>
      [item.label, item.path, group.label].some(value => value.toLocaleLowerCase().includes(term))),
  })).filter(group => group.items.length);

  return <div className="nfc-v2-sidebar nfc-v2-sidebar-mobile nfc-studio-tool-directory">
    <div className="nfc-studio-tool-search">
      <ConsoleIcon name="search" size={17} />
      <input ref={input} type="search" onKeyDown={event => {
        if (event.nativeEvent.isComposing || event.defaultPrevented) return;
        const first = list.current?.querySelector('a');
        if (first && event.key === 'ArrowDown') { event.preventDefault(); first.focus(); }
        if (first && term && event.key === 'Enter') { event.preventDefault(); first.click(); }
      }} aria-label="搜索工具" placeholder="搜索工具或页面" value={query}
        onChange={event => setQuery(event.target.value)} />
      {query && <button type="button" className="nfc-tool-search-clear" aria-label="清除工具搜索" onClick={() => {
        setQuery('');
        input.current?.focus({ preventScroll: true });
      }}><ConsoleIcon name="x" size={16} /></button>}
    </div>
    <nav className="nfc-v2-nav" ref={list} aria-label="主导航" onKeyDown={event => {
      if (!(event.target instanceof HTMLAnchorElement) || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const links = Array.from(event.currentTarget.querySelectorAll('a'));
      const index = links.indexOf(event.target);
      if (event.key === 'ArrowUp' && index === 0) { input.current?.focus(); return; }
      const target = event.key === 'Home' ? 0 : event.key === 'End' ? links.length - 1 :
        Math.min(links.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1));
      links[target]?.focus();
    }}>
      {groups.map(group => <section key={group.label} className="nfc-v2-nav-group" aria-label={group.label}>
        <h2 className="nfc-v2-nav-group-title">{group.label}</h2>
        {group.items.map(item => <Link key={item.path} to={item.path} onClick={onNavigate}
          aria-current={selectedKey === item.path ? 'page' : undefined}
          className={'nfc-v2-nav-item' + (selectedKey === item.path ? ' is-active' : '')}>
          <ConsoleIcon name={item.icon} size={17} /><span>{item.label}</span>
        </Link>)}
      </section>)}
      {!groups.length && <p className="nfc-studio-no-tools" role="status">没有找到匹配的工具</p>}
    </nav>
    <div className="nfc-v2-mobile-theme-switcher" role="group" aria-label="界面主题">
      <span className="nfc-v2-mobile-theme-label">界面主题</span>
      <div className="nfc-v2-mobile-theme-options">
        {([['light', '浅色模式'], ['dark', '深色模式'], ['system', '跟随系统']] as const).map(([key, label]) =>
          <button type="button" key={key} aria-pressed={mode === key}
            className={mode === key ? 'is-selected' : ''} onClick={() => { setMode(key); onNavigate(); }}>{label}</button>)}
      </div>
    </div>
    <div className="nfc-v2-sidebar-footer"><small className="nfc-v2-release-version">v2.0.7</small></div>
  </div>;
};
