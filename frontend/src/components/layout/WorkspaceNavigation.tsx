import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation } from 'react-router-dom';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { consoleNavGroups, currentDestination } from './navItems';
import { useCompactNavigationHint } from './useCompactNavigationHint';

/** Provide a single desktop navigation rail with a persistent toggle above its scroll area. */
export function WorkspaceNavigation({ compact, onToggleCompact }: {
  compact: boolean;
  onToggleCompact: () => void;
}) {
  const { pathname, search } = useLocation();
  const scrollArea = useRef<HTMLDivElement>(null);
  const destination = currentDestination(pathname, search);
  const toggleLabel = compact ? '展开主导航' : '收起主导航';
  const { hint, show, dismiss } = useCompactNavigationHint(compact, destination);
  /** Use the same visual label for pointer and keyboard interactions. */
  function hintEvents(label: string) {
    if (!compact) return {};
    return {
      onPointerEnter: (event: React.PointerEvent<HTMLElement>) => {
        if (event.pointerType !== 'touch') show(event.currentTarget, label);
      },
      onPointerLeave: dismiss,
      onFocus: (event: React.FocusEvent<HTMLElement>) => {
        if (event.currentTarget.matches(':focus-visible')) show(event.currentTarget, label, true);
      },
      onBlur: dismiss,
    };
  }
  useEffect(() => {
    const rail = scrollArea.current;
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
    <nav className="nfc-workspace-navigation" aria-label="主导航" data-compact={compact || undefined}
      onKeyDown={event => { if (event.key === 'Escape') dismiss(); }}>
      <div className="nfc-workspace-navigation-controls">
        <ConsoleButton size="sm" variant="ghost" aria-label={toggleLabel} title={compact ? undefined : toggleLabel}
          aria-controls="nfc-workspace-navigation-links" aria-expanded={!compact} onClick={onToggleCompact}
          {...hintEvents(toggleLabel)}
          leadingIcon={<ConsoleIcon name={compact ? 'panel-left-open' : 'panel-left-close'} size={17} />} />
      </div>
      <div ref={scrollArea} id="nfc-workspace-navigation-links" className="nfc-workspace-navigation-scroll" onScroll={dismiss}>
        {consoleNavGroups.map(group => (
          <section key={group.label} className="nfc-workspace-navigation-group" aria-label={group.label}>
            <p className="nfc-workspace-navigation-title" aria-hidden="true">{group.label}</p>
            {group.items.map(item => (
              <Link key={item.path} to={item.path} aria-current={destination === item.path ? 'page' : undefined}
                aria-label={compact ? item.label : undefined} onClick={dismiss} {...hintEvents(item.label)}>
                <ConsoleIcon name={item.icon} size={16} /><span>{item.label}</span>
              </Link>
            ))}
          </section>
        ))}
      </div>
      {hint && createPortal(<div key={hint.label} className="nfc-workspace-navigation-tooltip" aria-hidden="true"
        style={{ left: hint.x, top: hint.y }}>{hint.label}</div>, document.body)}
    </nav>
  );
}
