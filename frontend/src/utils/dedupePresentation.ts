import { formatBytes } from './format';

export interface EligibilityPresentation {
  text: string;
  status: 'eligible' | 'safety_excluded' | 'unavailable';
  tagColor: 'success' | 'warning' | 'default';
}

/**
 * Pure presentation helper for dedupe member eligibility.
 * true  -> 符合资格 (eligible)
 * false -> 安全排除 (safety_excluded)
 * undefined / null -> 不可用 / - (unavailable, fail-closed, strictly NEVER safety excluded)
 */
export function getEligibilityPresentation(eligible?: boolean | null): EligibilityPresentation {
  if (eligible === true) {
    return {
      text: '符合资格',
      status: 'eligible',
      tagColor: 'success',
    };
  }
  if (eligible === false) {
    return {
      text: '安全排除',
      status: 'safety_excluded',
      tagColor: 'warning',
    };
  }
  return {
    text: '不可用 / -',
    status: 'unavailable',
    tagColor: 'default',
  };
}

/**
 * Pure presentation helper for group ID display.
 * Numeric -> 组 #ID
 * undefined / null -> 组 - (Strictly forbids 组 #undefined)
 */
export function formatOptionalGroupId(groupId?: number | null): string {
  if (groupId !== undefined && groupId !== null) {
    return `组 #${groupId}`;
  }
  return '组 -';
}

/**
 * Pure presentation helper for single file size display.
 * Numeric -> formatted bytes (e.g. 1.2 MB)
 * undefined / null -> - (Strictly forbids calling formatBytes(undefined) resulting in 0 B)
 */
export function formatOptionalFileSize(bytes?: number | null): string {
  if (bytes !== undefined && bytes !== null) {
    return formatBytes(bytes);
  }
  return '-';
}

/**
 * Pure helper to verify if two dedupe rows can be grouped by provenance.
 * Only returns true if both items have a defined, non-null, and identical group_provenance_id.
 */
export function canCompareDedupeGroup(
  memberA: { group_provenance_id?: number | null },
  memberB: { group_provenance_id?: number | null }
): boolean {
  if (memberA.group_provenance_id === undefined || memberA.group_provenance_id === null) {
    return false;
  }
  if (memberB.group_provenance_id === undefined || memberB.group_provenance_id === null) {
    return false;
  }
  return memberA.group_provenance_id === memberB.group_provenance_id;
}

/**
 * Pure helper to filter sibling members of a duplicate group.
 * If member.group_provenance_id is missing/null, returns empty array to prevent
 * unrelated incomplete rows from being displayed as group siblings.
 */
export function findDuplicateGroupSiblings<
  T extends { group_provenance_id?: number | null; absolute_path: string }
>(member: T, groupMembers: T[]): T[] {
  if (member.group_provenance_id === undefined || member.group_provenance_id === null) {
    return [];
  }
  return groupMembers.filter(
    (m) =>
      m.group_provenance_id !== undefined &&
      m.group_provenance_id !== null &&
      m.group_provenance_id === member.group_provenance_id &&
      m.absolute_path !== member.absolute_path
  );
}

/**
 * Pure presentation helper for quarantine root.
 * String -> path
 * undefined / null -> 未配置 / null (Never fabricates paths)
 */
export function formatQuarantineRootPresentation(quarantineRoot?: string | null): string {
  if (quarantineRoot && typeof quarantineRoot === 'string' && quarantineRoot.trim()) {
    return quarantineRoot;
  }
  return '未配置 / null';
}

/**
 * Pure presentation helper for indexed allowed root display.
 */
export function formatAllowedRootPresentation(index: number, rootPath: string): string {
  return `Allowed Root ${index}: ${rootPath}`;
}

/**
 * Pure presentation helper for PROTECT_LAST_FILE policy description.
 */
export function getProtectLastFileDescription(protectLastFile?: boolean): string {
  if (protectLastFile === true) {
    return 'PROTECT_LAST_FILE 已启用：去重规划会执行目录级最后文件保护，避免计划隔离使受保护目录剩余文件数降到 0。具体排除原因以 backend safety_reasons 为准。';
  }
  if (protectLastFile === false) {
    return 'PROTECT_LAST_FILE 未启用。';
  }
  return 'PROTECT_LAST_FILE 未配置 / -';
}
