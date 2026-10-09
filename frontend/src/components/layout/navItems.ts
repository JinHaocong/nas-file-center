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
  { label: '工作台', items: [
    { path: '/dashboard', label: '仪表盘', icon: 'layout-dashboard' },
  ] },
  { label: '数据与扫描', items: [
    { path: '/indexes', label: '文件索引', icon: 'database' },
    { path: '/scans', label: '精确去重', icon: 'layers' },
    { path: '/media', label: '媒体完整性', icon: 'file-check' },
  ] },
  { label: '文件工具', items: [
    { path: '/path-match', label: '路径匹配', icon: 'folder-open' },
    { path: '/directory-diff', label: '双目录差异', icon: 'git-compare' },
    { path: '/rename', label: '批量重命名', icon: 'pencil' },
    { path: '/batch', label: '批量处理', icon: 'folders' },
    { path: '/organizer', label: 'Organizer 整理', icon: 'folder' },
    { path: '/filename-audit', label: '文件名巡检', icon: 'file-search' },
  ] },
  { label: '自动化', items: [
    { path: '/workflows', label: '工作流中心', icon: 'workflow' },
    { path: '/schedules', label: '计划任务', icon: 'calendar' },
  ] },
  { label: '安全与运行', items: [
    { path: '/plans', label: '执行计划', icon: 'list-checks' },
    { path: '/quarantine', label: '文件隔离区', icon: 'archive' },
    { path: '/tasks', label: '任务中心', icon: 'activity' },
    { path: '/audit', label: '审计日志', icon: 'file-text' },
  ] },
  { label: '系统', items: [
    { path: '/settings', label: '系统设置', icon: 'settings' },
  ] },
];

export const consoleNavigation = consoleNavGroups.flatMap(group => group.items);

export function navLabel(pathname: string): string {
  const root = '/' + pathname.split('/')[1];
  return consoleNavigation.find(item => item.path === root)?.label || '工作台';
}
