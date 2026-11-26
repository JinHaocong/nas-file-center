import type { ConsoleIconName } from '../ui/ConsoleIcon';

export interface ConsoleNavItem {
  path: string;
  label: string;
  icon: ConsoleIconName;
}
export interface ConsoleNavGroup {
  label: string;
  items: ConsoleNavItem[];
}

export const consoleNavGroups: ConsoleNavGroup[] = [
  { label: '我的文件', items: [
    { path: '/dashboard', label: '文件空间', icon: 'hard-drive' },
    { path: '/batch?operation=media-organize', label: '智能媒体整理', icon: 'folders' },
    { path: '/indexes', label: '文件索引', icon: 'database' },
    { path: '/media', label: '媒体完整性', icon: 'file-check' },
  ] },
  { label: '查找与核对', items: [
    { path: '/scans', label: '精确去重', icon: 'layers' },
    { path: '/path-match', label: '路径匹配', icon: 'folder-open' },
    { path: '/directory-diff', label: '双目录差异', icon: 'git-compare' },
    { path: '/filename-audit', label: '文件名巡检', icon: 'file-search' },
    { path: '/download-verification', label: '下载完整性校验', icon: 'file-check' },
    { path: '/download-sources', label: '下载校验来源', icon: 'database' },
  ] },
  { label: '整理与恢复', items: [
    { path: '/rename', label: '批量重命名', icon: 'pencil' },
    { path: '/batch', label: '批量处理', icon: 'folders' },
    { path: '/organizer', label: '目录整理方案', icon: 'folder' },
    { path: '/archive-recovery', label: '压缩包恢复', icon: 'archive' },
    { path: '/quarantine', label: '文件隔离区', icon: 'archive' },
  ] },
  { label: '任务与设置', items: [
    { path: '/tasks', label: '任务中心', icon: 'activity' },
    { path: '/plans', label: '执行计划', icon: 'list-checks' },
    { path: '/workflows', label: '工作流中心', icon: 'workflow' },
    { path: '/schedules', label: '计划任务', icon: 'calendar' },
    { path: '/audit', label: '审计日志', icon: 'file-text' },
    { path: '/settings', label: '系统设置', icon: 'settings' },
  ] },
];

export const consoleNavigation = consoleNavGroups.flatMap(group => group.items);

export const primaryDestinations: ConsoleNavItem[] = [
  { path: '/dashboard', label: '文件空间', icon: 'hard-drive' },
  { path: '/batch?operation=media-organize', label: '整理', icon: 'folders' },
  { path: '/scans', label: '扫描', icon: 'layers' },
  { path: '/tasks', label: '记录', icon: 'clock' },
];

/** A reopened preview or batch belongs to media organization as well. */
export function currentDestination(pathname: string, search: string): string {
  const root = '/' + pathname.split('/')[1];
  if (root === '/batch') {
    const params = new URLSearchParams(search);
    if (['media-organize', 'media_package-organize', 'semantic-media-organize'].includes(params.get('operation') ?? '') ||
        ['execution', 'batch', 'preview'].some(key => params.has(key))) {
      return '/batch?operation=media-organize';
    }
  }
  return root;
}

/** Return the user-facing name of the current workspace. */
export function navLabel(pathname: string, search = ''): string {
  const destination = currentDestination(pathname, search);
  return consoleNavigation.find(item => item.path === destination)?.label ?? '文件空间';
}

/** Document workspaces own their location rail; tool routes use their navigation group. */
export function workspaceNavigationGroup(pathname: string, search = ''): ConsoleNavGroup | undefined {
  const destination = currentDestination(pathname, search);
  if (destination === '/dashboard' || destination === '/batch?operation=media-organize') return undefined;
  return consoleNavGroups.find(group => group.items.some(item => item.path === destination));
}

/** Folder history has its own scroll position; selection and filter changes keep the current view. */
export function workspaceViewKey(pathname: string, search: string): string {
  if (pathname !== '/dashboard') return pathname;
  const params = new URLSearchParams(search);
  const view = params.get('view') === 'overview' ? 'overview' : params.get('directory') ?? '';
  return pathname + ':' + view;
}
