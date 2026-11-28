import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { ConsoleIcon } from '../ui/ConsoleIcon';
import { consoleNavGroups, currentDestination } from './navItems';

/** Provide a single desktop navigation rail, with a compact mode beside a directory rail. */
export function WorkspaceNavigation({ compact }: { compact: boolean }) {
  const { pathname, search } = useLocation();
  const nav = useRef<HTMLElement>(null);
  const destination = currentDestination(pathname, search);
  useEffect(() => {
    const rail = nav.current;
    const current = rail?.querySelector('[aria-current="page"]');
    if (!rail || !current || !rail.clientHeight) return;
    // Only the navigation rail should move when a direct link opens a tool.
    const railBounds = rail.getBoundingClientRect();
    const itemBounds = current.getBoundingClientRect();
    if (itemBounds.top < railBounds.top + 8) {
      rail.scrollTop += itemBounds.top - railBounds.top - 8;
    } else if (itemBounds.bottom > railBounds.bottom - 8) {
      rail.scrollTop += itemBounds.bottom - railBounds.bottom + 8;
    }
  }, [destination, compact]);

  return (
    <nav ref={nav} className="nfc-workspace-navigation" aria-label="主导航"
      data-compact={compact || undefined}>
      {consoleNavGroups.map(group => (
        <section key={group.label} className="nfc-workspace-navigation-group" aria-label={group.label}>
          <p className="nfc-workspace-navigation-title" aria-hidden="true">{group.label}</p>
          {group.items.map(item => (
            <Link key={item.path} to={item.path} aria-current={destination === item.path ? 'page' : undefined}
              aria-label={compact ? item.label : undefined} title={compact ? item.label : undefined}>
              <ConsoleIcon name={item.icon} size={16} /><span>{item.label}</span>
            </Link>
          ))}
        </section>
      ))}
    </nav>
  );
}
