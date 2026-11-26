import { Link, useLocation } from 'react-router-dom';

import { ConsoleIcon } from '../ui/ConsoleIcon';
import { currentDestination, workspaceNavigationGroup } from './navItems';

/** Keep related tools visible while respecting the folder workspace's own location rail. */
export function WorkspaceNavigation() {
  const { pathname, search } = useLocation();
  const group = workspaceNavigationGroup(pathname, search);
  if (!group) return null;
  const destination = currentDestination(pathname, search);
  return (
    <nav className="nfc-workspace-navigation" aria-label={group.label}>
      <Link to="/dashboard" className="nfc-workspace-home"><ConsoleIcon name="hard-drive" size={16} />文件空间</Link>
      <p className="nfc-workspace-navigation-title">{group.label}</p>
      {group.items.map(item => (
        <Link key={item.path} to={item.path} aria-current={destination === item.path ? 'page' : undefined}>
          <ConsoleIcon name={item.icon} size={16} />{item.label}
        </Link>
      ))}
    </nav>
  );
}
