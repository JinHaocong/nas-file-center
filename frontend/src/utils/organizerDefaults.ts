import { OrganizerProfileSnapshot } from '../types/workflow';

export function createDefaultOrganizerSnapshot(name = ''): OrganizerProfileSnapshot {
  return {
    name,
    description: '',
    root: '',
    recursive: false,
    image_extensions: ['jpg', 'jpeg', 'png', 'webp'],
    video_extensions: ['mp4', 'mov', 'mkv'],
    rename_template: '{name}',
    statistics_template: '[{images}P {videos}V {size}]',
    preserve_tags: [],
    cleanup_patterns: [],
    numbering_mode: 'none',
    numbering_start: 1,
    numbering_padding: 3,
    mtime_mode: 'none',
    mtime_delay_seconds: 2.0,
  };
}
