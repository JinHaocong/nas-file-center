import React from 'react';
import {
  Activity, Archive, ArrowRight, Bell, CalendarDays, Check,
  CircleCheck, ChevronDown, ChevronRight, Clock3, Database,
  FileCheck2, FileSearch, FileText, Folder, FolderOpen, Folders,
  GitCompareArrows, HardDrive, Layers3, LayoutDashboard, ListChecks,
  LockKeyhole, LogOut, Menu, Moon, Pencil, Play, RefreshCw,
  Search, Settings, ShieldCheck, SlidersHorizontal, Sun,
  Terminal, UserRound, Workflow, X, Zap,
} from 'lucide-react';
import type { LucideIcon, LucideProps } from 'lucide-react';

/** Named icon vocabulary stays stable as product routes migrate. */
const icons = {
  activity: Activity,
  archive: Archive,
  'arrow-right': ArrowRight,
  bell: Bell,
  calendar: CalendarDays,
  check: Check,
  'check-circle': CircleCheck,
  'chevron-down': ChevronDown,
  'chevron-right': ChevronRight,
  clock: Clock3,
  database: Database,
  'file-check': FileCheck2,
  'file-search': FileSearch,
  'file-text': FileText,
  folder: Folder,
  'folder-open': FolderOpen,
  folders: Folders,
  'git-compare': GitCompareArrows,
  'hard-drive': HardDrive,
  layers: Layers3,
  'layout-dashboard': LayoutDashboard,
  'list-checks': ListChecks,
  lock: LockKeyhole,
  'log-out': LogOut,
  menu: Menu,
  moon: Moon,
  pencil: Pencil,
  play: Play,
  refresh: RefreshCw,
  search: Search,
  settings: Settings,
  'shield-check': ShieldCheck,
  sliders: SlidersHorizontal,
  sun: Sun,
  terminal: Terminal,
  user: UserRound,
  workflow: Workflow,
  x: X,
  zap: Zap,
} satisfies Record<string, LucideIcon>;

export type ConsoleIconName = keyof typeof icons;

interface Props extends Omit<LucideProps, 'size'> {
  name: ConsoleIconName;
  size?: number;
}

export const ConsoleIcon: React.FC<Props> = ({
  name, size = 20, 'aria-hidden': ariaHidden = true, ...props
}) => {
  const Icon = icons[name];
  return <Icon size={size} strokeWidth={1.85} aria-hidden={ariaHidden} {...props} />;
};
