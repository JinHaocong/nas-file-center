import { OrganizerProfileSnapshot, CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS } from '../types/workflow';

export { CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS };

export function createDefaultOrganizerSnapshot(name = ''): OrganizerProfileSnapshot {
  return {
    ...CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS,
    name,
    image_extensions: [...(CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS.image_extensions || [])],
    video_extensions: [...(CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS.video_extensions || [])],
    preserve_tags: [...(CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS.preserve_tags || [])],
    cleanup_patterns: [...(CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS.cleanup_patterns || [])],
  };
}

export function importProfileToSnapshot(p: {
  name?: string;
  description?: string | null;
  root?: string | null;
  recursive?: boolean;
  image_extensions?: string[];
  video_extensions?: string[];
  rename_template?: string;
  statistics_template?: string;
  preserve_tags?: string[];
  cleanup_patterns?: string[];
  numbering_mode?: 'none' | 'sequential';
  numbering_start?: number;
  numbering_padding?: number;
  mtime_mode?: 'none' | 'ordered';
  mtime_delay_seconds?: number;
}): OrganizerProfileSnapshot {
  return {
    name: p.name || '未命名整理方案',
    description: p.description ?? '',
    root: p.root ?? '',
    recursive: p.recursive ?? false,
    image_extensions: p.image_extensions ? [...p.image_extensions] : ['jpg', 'jpeg', 'png', 'webp'],
    video_extensions: p.video_extensions ? [...p.video_extensions] : ['mp4', 'mov', 'mkv'],
    rename_template: p.rename_template || '{name}',
    statistics_template: p.statistics_template || '[{images}P {videos}V {size}]',
    preserve_tags: p.preserve_tags ? [...p.preserve_tags] : [],
    cleanup_patterns: p.cleanup_patterns ? [...p.cleanup_patterns] : [],
    numbering_mode: p.numbering_mode || 'none',
    numbering_start: p.numbering_start ?? 1,
    numbering_padding: p.numbering_padding ?? 3,
    mtime_mode: p.mtime_mode || 'none',
    mtime_delay_seconds: p.mtime_delay_seconds ?? 2.0,
  };
}
