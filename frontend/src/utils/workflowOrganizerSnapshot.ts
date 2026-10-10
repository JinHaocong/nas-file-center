import type { OrganizerAdvancedRules, OrganizerProfileSnapshot } from '../types/workflow';
import { cloneOrganizerAdvancedRules, createDefaultOrganizerSnapshot } from './organizerDefaults';

/** Form defaults are for display only; arrays and nested rules are never aliased. */
export function hydrateWorkflowOrganizerSnapshot(snapshot: OrganizerProfileSnapshot): OrganizerProfileSnapshot {
  const defaults = createDefaultOrganizerSnapshot();
  return {
    ...defaults,
    ...snapshot,
    name: snapshot.name || '',
    description: snapshot.description || '',
    root: snapshot.root || '',
    recursive: snapshot.recursive ?? defaults.recursive,
    image_extensions: [...(snapshot.image_extensions ?? defaults.image_extensions ?? [])],
    video_extensions: [...(snapshot.video_extensions ?? defaults.video_extensions ?? [])],
    rename_template: snapshot.rename_template ?? defaults.rename_template,
    statistics_template: snapshot.statistics_template ?? defaults.statistics_template,
    preserve_tags: [...(snapshot.preserve_tags ?? defaults.preserve_tags ?? [])],
    cleanup_patterns: [...(snapshot.cleanup_patterns ?? defaults.cleanup_patterns ?? [])],
    numbering_mode: snapshot.numbering_mode ?? defaults.numbering_mode,
    numbering_start: snapshot.numbering_start ?? defaults.numbering_start,
    numbering_padding: snapshot.numbering_padding ?? defaults.numbering_padding,
    mtime_mode: snapshot.mtime_mode ?? defaults.mtime_mode,
    mtime_delay_seconds: snapshot.mtime_delay_seconds ?? defaults.mtime_delay_seconds,
    advanced_rules: cloneOrganizerAdvancedRules(snapshot.advanced_rules ?? defaults.advanced_rules),
  };
}

/** Mirror the former Ant Form onValuesChange transport; never drop advanced_rules. */
export function normalizeWorkflowOrganizerSnapshot(values: OrganizerProfileSnapshot): OrganizerProfileSnapshot {
  const fields = hydrateWorkflowOrganizerSnapshot(values);
  return {
    ...fields,
    name: fields.name,
    description: fields.description || null,
    root: fields.root || null,
    recursive: Boolean(fields.recursive),
    image_extensions: [...(fields.image_extensions || [])],
    video_extensions: [...(fields.video_extensions || [])],
    rename_template: fields.rename_template || '{name}',
    statistics_template: fields.statistics_template || '[{images}P {videos}V {size}]',
    preserve_tags: [...(fields.preserve_tags || [])],
    cleanup_patterns: [...(fields.cleanup_patterns || [])],
    numbering_mode: fields.numbering_mode || 'none',
    numbering_start: Number(fields.numbering_start ?? 1),
    numbering_padding: Number(fields.numbering_padding ?? 3),
    mtime_mode: fields.mtime_mode || 'none',
    mtime_delay_seconds: Number(fields.mtime_delay_seconds ?? 2.0),
    advanced_rules: cloneOrganizerAdvancedRules(fields.advanced_rules),
  };
}

export function patchWorkflowOrganizerSnapshot<K extends keyof OrganizerProfileSnapshot>(
  snapshot: OrganizerProfileSnapshot,
  field: K,
  value: OrganizerProfileSnapshot[K],
): OrganizerProfileSnapshot {
  return normalizeWorkflowOrganizerSnapshot({
    ...hydrateWorkflowOrganizerSnapshot(snapshot),
    [field]: value,
  });
}

export type OrganizerRuleKey = keyof Omit<OrganizerAdvancedRules, 'version'>;
export function patchWorkflowOrganizerAdvancedRule(
  snapshot: OrganizerProfileSnapshot,
  key: OrganizerRuleKey,
  fields: Record<string, unknown>,
): OrganizerProfileSnapshot {
  const current = hydrateWorkflowOrganizerSnapshot(snapshot);
  const advancedRules = cloneOrganizerAdvancedRules(current.advanced_rules);
  const updated = {
    ...advancedRules,
    [key]: { ...advancedRules[key], ...fields },
  };
  return normalizeWorkflowOrganizerSnapshot({ ...current, advanced_rules: updated });
}

export function validateWorkflowOrganizerSnapshot(snapshot: OrganizerProfileSnapshot): string[] {
  const fields = hydrateWorkflowOrganizerSnapshot(snapshot);
  const a = cloneOrganizerAdvancedRules(fields.advanced_rules);
  const enabled = a.directory_depth.enabled || a.file_numbering.enabled ||
    a.latest_child_prefix.enabled || a.single_child_wrapper_collapse.enabled;
  const errors: string[] = [];
  if (!fields.name.trim()) errors.push('方案/快照名称不能为空');
  if (!fields.rename_template?.trim()) errors.push('目录重命名模板不能为空');
  if (!fields.statistics_template?.trim()) errors.push('统计标签模板不能为空');
  if (enabled && !fields.recursive) errors.push('启用 Advanced Rules 时必须开启递归处理子目录');
  if (a.latest_child_prefix.enabled && fields.mtime_mode === 'ordered') {
    errors.push('Latest-child prefix 与 ordered mtime 不兼容');
  }
  if (a.latest_child_prefix.enabled && !a.latest_child_prefix.prefix.trim()) {
    errors.push('Latest-child prefix 启用时必须提供非空前缀');
  }
  if (a.directory_depth.enabled && (a.directory_depth.rename_from_depth < 2 || a.directory_depth.rename_from_depth > 64)) {
    errors.push('开始重命名深度须在 2 到 64 之间');
  }
  return errors;
}
