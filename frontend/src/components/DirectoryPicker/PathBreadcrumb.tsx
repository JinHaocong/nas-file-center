import React from 'react';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { buildDirectoryBreadcrumb } from './path_model';

interface PathBreadcrumbProps {
  currentPath: string;
  allowedRoots?: string[];
  onNavigate: (path: string) => void;
}

/** Breadcrumb navigation derives only from the server-reported allowed roots. */
export const PathBreadcrumb: React.FC<PathBreadcrumbProps> = ({
  currentPath, allowedRoots = [], onNavigate,
}) => {
  const location = buildDirectoryBreadcrumb(currentPath, allowedRoots);
  if (!location) return null;

  const roots = [...new Set(allowedRoots.map(root => root.replace(/\/+$/, '') || '/'))];

  return (
    <nav className="nfc-path-breadcrumb nfc-v2-path-breadcrumb" aria-label="目录位置">
      {roots.length > 1 ? (
        <label className="nfc-v2-breadcrumb-root-select">
          <ConsoleIcon name="folder" size={15} />
          <select aria-label="切换允许的根目录" value={location.baseRoot}
            onChange={event => onNavigate(event.target.value)}>
            {roots.map(root => <option key={root} value={root}>{root}</option>)}
          </select>
          <ConsoleIcon name="chevron-down" size={13} />
        </label>
      ) : (
        <button type="button" className="nfc-v2-breadcrumb-link nfc-path-breadcrumb-root"
          onClick={() => onNavigate(location.baseRoot)}>
          <ConsoleIcon name="folder" size={15} />
          <span>{location.baseRoot}</span>
        </button>
      )}
      {location.segments.map((segment, index) => (
        <React.Fragment key={segment.path}>
          <ConsoleIcon name="chevron-right" size={13} className="nfc-v2-breadcrumb-separator" />
          {index === location.segments.length - 1 ? (
            <span className="nfc-path-breadcrumb-current" aria-current="location">
              {segment.name}
            </span>
          ) : (
            <button type="button" className="nfc-v2-breadcrumb-link nfc-path-breadcrumb-link"
              onClick={() => onNavigate(segment.path)}>
              {segment.name}
            </button>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
};
