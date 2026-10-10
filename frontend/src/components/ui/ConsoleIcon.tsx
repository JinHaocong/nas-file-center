import React from 'react';
import {
  Activity, Archive, ArrowDown, ArrowRight, ArrowUp, Bell, CalendarDays, Check,
  CircleCheck, ChevronDown, ChevronRight, Clock3, Database,
  FileCheck2, FileSearch, FileText, Folder, FolderOpen, Folders,
  GitCompareArrows, HardDrive, History, Info, Layers3, LayoutDashboard, ListChecks,
  LockKeyhole, LogOut, Menu, Moon, Pencil, Play, Plus, RefreshCw,
  Search, Settings, ShieldCheck, SlidersHorizontal, Star, Sun, Trash2,
  Terminal, UserRound, Workflow, X, Zap,
} from 'lucide-react';
import type { LucideIcon, LucideProps } from 'lucide-react';

/** Named icon vocabulary stays stable as product routes migrate. */
const icons = {
  activity: Activity,
  archive: Archive,
  'arrow-up': ArrowUp,
  'arrow-down': ArrowDown,
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
  history: History,
  info: Info,
  layers: Layers3,
  'layout-dashboard': LayoutDashboard,
  'list-checks': ListChecks,
  lock: LockKeyhole,
  'log-out': LogOut,
  menu: Menu,
  moon: Moon,
  pencil: Pencil,
  play: Play,
  plus: Plus,
  refresh: RefreshCw,
  search: Search,
  settings: Settings,
  'shield-check': ShieldCheck,
  sliders: SlidersHorizontal,
  star: Star,
  sun: Sun,
  trash: Trash2,
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
