import type { OrganizerProfile } from '../types';
import type { OrganizerProfileSnapshot } from '../types/workflow';
import { createDefaultOrganizerSnapshot } from './organizerDefaults';
import { hydrateWorkflowOrganizerSnapshot, normalizeWorkflowOrganizerSnapshot, validateWorkflowOrganizerSnapshot } from './workflowOrganizerSnapshot';

/** Standalone profiles are independent from Workflow snapshot identity and immutable metadata. */
export function initialOrganizerProfileForm(profile: OrganizerProfile | null): OrganizerProfileSnapshot {
  if (!profile) return createDefaultOrganizerSnapshot();
  return hydrateWorkflowOrganizerSnapshot({
    name: profile.name,
    description: profile.description || '',
    root: profile.root || '',
    recursive: profile.recursive,
    image_extensions: profile.image_extensions,
    video_extensions: profile.video_extensions,
    rename_template: profile.rename_template,
    statistics_template: profile.statistics_template,
    preserve_tags: profile.preserve_tags,
    cleanup_patterns: profile.cleanup_patterns,
    numbering_mode: profile.numbering_mode,
    numbering_start: profile.numbering_start,
    numbering_padding: profile.numbering_padding,
    mtime_mode: profile.mtime_mode,
    mtime_delay_seconds: profile.mtime_delay_seconds,
    advanced_rules: profile.advanced_rules,
  });
}

/** Submit editable schema fields ONLY. Never send id, user_id, is_builtin or timestamps. */
export function organizerProfileFormPayload(values: OrganizerProfileSnapshot): Partial<OrganizerProfile> {
  const normalized = normalizeWorkflowOrganizerSnapshot(values);
  return {
    name: normalized.name,
    description: normalized.description || '',
    root: normalized.root || '',
    recursive: Boolean(normalized.recursive),
    image_extensions: [...(normalized.image_extensions || [])],
    video_extensions: [...(normalized.video_extensions || [])],
    rename_template: normalized.rename_template,
    statistics_template: normalized.statistics_template,
    preserve_tags: [...(normalized.preserve_tags || [])],
    cleanup_patterns: [...(normalized.cleanup_patterns || [])],
    numbering_mode: normalized.numbering_mode,
    numbering_start: normalized.numbering_start,
    numbering_padding: normalized.numbering_padding,
    mtime_mode: normalized.mtime_mode,
    mtime_delay_seconds: normalized.mtime_delay_seconds,
    advanced_rules: normalized.advanced_rules,
  };
}

export function canSubmitOrganizerProfileForm(
  draft: OrganizerProfileSnapshot,
  editing: OrganizerProfile | null,
  busy: boolean,
): boolean {
  if (busy || Boolean(editing?.is_builtin)) return false;
  return validateWorkflowOrganizerSnapshot(draft).length === 0;
}
