import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { currentDestination, primaryDestinations } from './navItems';

interface Props {
  moreOpen: boolean;
  onMore: React.MouseEventHandler<HTMLButtonElement>;
}

/** Keep the selected destination visible across nested routes and organizer reports. */
export const MobileDock: React.FC<Props> = ({ moreOpen, onMore }) => {
  const location = useLocation();
  const current = currentDestination(location.pathname, location.search);
  const activeTab = primaryDestinations.findIndex(item => item.path === current);
  const moreActive = moreOpen || activeTab < 0;
  const indicatorStyle = { '--nfc-dock-index': moreActive ? primaryDestinations.length : activeTab } as React.CSSProperties;
  return <nav className="nfc-mobile-dock nfc-v2-mobile-dock" aria-label="移动端快捷导航">
    <div className="nfc-mobile-dock-surface" style={indicatorStyle}>
      <span className="nfc-mobile-dock-track" aria-hidden="true"><span className="nfc-mobile-dock-marker" /></span>
      {primaryDestinations.map((item, index) => <Link key={item.path} to={item.path}
        aria-current={activeTab === index ? 'page' : undefined}
        className={'nfc-mobile-dock-item' + (!moreOpen && activeTab === index ? ' is-active' : '')}>
        <ConsoleIcon name={item.icon} size={19} /><span>{item.label}</span>
      </Link>)}
      <button type="button" className={'nfc-mobile-dock-item' + (moreActive ? ' is-active' : '')}
        aria-haspopup="dialog" aria-expanded={moreOpen} onClick={onMore}>
        <ConsoleIcon name="menu" size={19} /><span>更多</span>
      </button>
    </div>
  </nav>;
};
