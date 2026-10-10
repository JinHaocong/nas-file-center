import type { OrganizerProfile } from '../types';

/** Import the exported envelope as-is; enforce just its basic shape before server validation. */
export interface OrganizerProfileImportEnvelope {
  schema_version: number;
  profile: Record<string, unknown>;
}
export function parseOrganizerProfileImport(text: string): OrganizerProfileImportEnvelope {
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('导入内容必须是 JSON 对象');
  }
  const object = parsed as Record<string, unknown>;
  if (!Number.isSafeInteger(object.schema_version) || (object.schema_version as number) < 1 ||
      !object.profile || typeof object.profile !== 'object' || Array.isArray(object.profile)) {
    throw new Error('缺少有效的 schema_version 或 profile 对象，请使用方案导出文件');
  }
  return { schema_version: object.schema_version as number, profile: object.profile as Record<string, unknown> };
}
/** Never treat stale/different-page results as a delete authorization. */
export function resolveOrganizerProfileDelete(
  intent: { id: number; name: string } | null, items: readonly OrganizerProfile[],
  busy: boolean,
): OrganizerProfile | null {
  if (!intent || busy) return null;
  const current = items.find(p => p.id === intent.id);
  return current && !current.is_builtin && current.name === intent.name ? current : null;
}
export function organizerExportFilename(profileName: string): string {
  const sanitized = profileName.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').trim().slice(0, 100);
  return 'organizer-profile-' + (sanitized || 'export') + '.json';
}
