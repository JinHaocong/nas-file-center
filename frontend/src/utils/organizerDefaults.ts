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
