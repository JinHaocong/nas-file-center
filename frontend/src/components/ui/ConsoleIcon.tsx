import React from 'react';

/**
 * Dependency-free outline icon bridge for the first console migration phase.
 * Paths follow the open, 24px/2px stroke icon vocabulary used by Lucide.
 * A single bridge keeps the app shell independent of the old Ant icon runtime.
 */
export type ConsoleIconName =
  | 'activity' | 'archive' | 'arrow-right' | 'bell' | 'calendar'
  | 'check' | 'check-circle' | 'chevron-down' | 'chevron-right'
  | 'clock' | 'database' | 'file-check' | 'file-search' | 'file-text'
  | 'folder' | 'folder-open' | 'folders' | 'git-compare' | 'hard-drive'
  | 'layers' | 'layout-dashboard' | 'list-checks' | 'lock' | 'log-out'
  | 'menu' | 'moon' | 'pencil' | 'play' | 'refresh' | 'search'
  | 'settings' | 'shield-check' | 'sliders' | 'sun' | 'terminal'
  | 'user' | 'workflow' | 'x' | 'zap';

const paths: Record<ConsoleIconName, string> = {
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  archive: 'M3 4h18v4H3z M5 8v12h14V8 M10 12h4',
  'arrow-right': 'M5 12h14 M13 6l6 6-6 6',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4',
  calendar: 'M4 5h16v16H4z M8 3v4 M16 3v4 M4 10h16',
  check: 'M4 12l5 5L20 6',
  'check-circle': 'M21 11v1a9 9 0 1 1-5-8 M9 12l3 3 8-9',
  'chevron-down': 'M6 9l6 6 6-6',
  'chevron-right': 'M9 6l6 6-6 6',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2',
  database: 'M3 6c0-2 4-3 9-3s9 1 9 3-4 3-9 3-9-1-9-3z M3 6v6c0 2 4 3 9 3s9-1 9-3V6 M3 12v6c0 2 4 3 9 3s9-1 9-3v-6',
  'file-check': 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 15l3 3 5-6',
  'file-search': 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h5 M14 2v6h6 M16 16a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M19 22l3 3',
  'file-text': 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8',
  folder: 'M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  'folder-open': 'M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v2 M3 13h19l-3 8H5z',
  folders: 'M3 7a2 2 0 0 1 2-2h4l2 3h7a2 2 0 0 1 2 2v9H3z M8 3h5l2 3h6v11',
  'git-compare': 'M5 5v14 M5 5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M5 23a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M19 5v14 M19 5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M19 23a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M8 12h8 M13 9l3 3-3 3',
  'hard-drive': 'M4 5h16l2 11v3a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-3z M2 16h20 M6 19h.01 M10 19h.01',
  layers: 'M12 2l10 6-10 6L2 8z M2 12l10 6 10-6 M2 16l10 6 10-6',
  'layout-dashboard': 'M3 3h8v8H3z M15 3h6v5h-6z M15 12h6v9h-6z M3 15h8v6H3z',
  'list-checks': 'M10 6h11 M10 12h11 M10 18h11 M3 6l2 2 3-4 M3 12l2 2 3-4 M3 18l2 2 3-4',
  lock: 'M5 11h14v11H5z M8 11V7a4 4 0 1 1 8 0v4 M12 15v3',
  'log-out': 'M10 4H4v16h6 M13 8l4 4-4 4 M7 12h10',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  moon: 'M20 15a8 8 0 0 1-11-11 9 9 0 1 0 11 11z',
  pencil: 'M4 20l5-.8L21 7a3 3 0 0 0-4-4L5 15z M14 6l4 4',
  play: 'M7 4l14 8-14 8z',
  refresh: 'M20 7v5h-5 M4 17v-5h5 M5 9a8 8 0 0 1 14-2l1 5 M4 12l1 5a8 8 0 0 0 14-2',
  search: 'M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16z M17 17l5 5',
  settings: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M4 10l-2 2 2 2 1 3 3 1 2 3h4l2-3 3-1 1-3 2-2-2-2-1-3-3-1-2-3h-4L8 6 5 7z',
  'shield-check': 'M12 2l9 4v6c0 6-4 9-9 11-5-2-9-5-9-11V6z M8 12l3 3 5-6',
  sliders: 'M4 6h16 M4 12h16 M4 18h16 M8 4v4 M16 10v4 M10 16v4',
  sun: 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z M12 1v3 M12 20v3 M1 12h3 M20 12h3 M4 4l2 2 M18 18l2 2 M4 20l2-2 M18 6l2-2',
  terminal: 'M3 4h18v16H3z M7 9l4 3-4 3 M13 16h5',
  user: 'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M4 21a8 8 0 0 1 16 0',
  workflow: 'M4 4h6v6H4z M14 14h6v6h-6z M7 10v7h7 M14 7h6 M17 4v6',
  x: 'M5 5l14 14 M19 5L5 19',
  zap: 'M13 2L3 14h8l-1 8 11-13h-8z',
};

interface Props extends React.SVGProps<SVGSVGElement> {
  name: ConsoleIconName;
  size?: number;
}

export const ConsoleIcon: React.FC<Props> = ({ name, size = 20, ...props }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    strokeWidth={1.85}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <path d={paths[name]} />
  </svg>
);
