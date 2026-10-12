import type { PathMatchGroup, PathMatchPreviewResponse } from '../api/domain';

export type PathMatchMode = 'relative-path' | 'basename' | 'stem' | 'normalized';
export interface PathMatchRequest {
  roots: string[];
  mode: PathMatchMode;
  normalize_pattern: string | null;
  normalize_replacement: string;
}
export interface PathMatchPlanItem {
  operation: 'quarantine';
  source: string;
  keep: string;
  expected_size: number;
}

export function buildPathMatchRequest(
  roots: readonly string[], mode: PathMatchMode,
  pattern: string, replacement: string,
): PathMatchRequest | null {
  // Let the server canonicalize roots and enforce ALLOWED_ROOTS and symlink policies.
  if (roots.length < 2 || roots.some(root => typeof root !== 'string' || !root.trim()) ||
      new Set(roots).size !== roots.length ||
      !['relative-path', 'basename', 'stem', 'normalized'].includes(mode)) return null;
  if (mode === 'normalized' && !pattern.trim()) return null;
  return {
    roots: [...roots], mode,
    normalize_pattern: mode === 'normalized' ? pattern : null,
    normalize_replacement: mode === 'normalized' ? replacement : '',
  };
}

function isValidMember(member: PathMatchGroup['members'][number]): boolean {
  return !!member &&
    typeof member.root === 'string' && member.root.length > 0 &&
    typeof member.path === 'string' && member.path.startsWith('/') &&
    typeof member.relative_path === 'string' && member.relative_path.length > 0 &&
    typeof member.size === 'number' && Number.isSafeInteger(member.size) && member.size >= 0 &&
    typeof member.mtime_ns === 'number' && Number.isFinite(member.mtime_ns);
}

function canonicalGroupData(report: PathMatchPreviewResponse): string | null {
  if (!report || !Array.isArray(report.groups) ||
      typeof report.count !== 'number' || !Number.isSafeInteger(report.count) ||
      report.count < 0 || report.count !== report.groups.length) return null;
  const keys = new Set<string>();
  const allPaths = new Set<string>();
  for (const group of report.groups) {
    if (!group || typeof group.key !== 'string' || !group.key ||
        keys.has(group.key) || !Array.isArray(group.members) || group.members.length < 2) return null;
    keys.add(group.key);
    for (const member of group.members) {
      if (!isValidMember(member) || allPaths.has(member.path)) return null;
      allPaths.add(member.path);
    }
  }
  // Preserve group order, the server's first-member keep, and every file snapshot field.
  return JSON.stringify(report.groups.map(group => ({
    key: group.key,
    members: group.members.map(member => ({
      root: member.root, path: member.path,
      relative_path: member.relative_path, size: member.size, mtime_ns: member.mtime_ns,
    })),
  })));
}

/** Freeze/Validate remains server authority; this only builds an unchanged, re-previewed Draft. */
export function buildPathMatchPlanItems(
  original: PathMatchPreviewResponse,
  fresh: PathMatchPreviewResponse,
): PathMatchPlanItem[] | null {
  const before = canonicalGroupData(original);
  const after = canonicalGroupData(fresh);
  if (before === null || after === null || before !== after) return null;
  const items: PathMatchPlanItem[] = [];
  const keepPaths = new Set<string>();
  const sourcePaths = new Set<string>();
  for (const g of original.groups) {
    const keep = g.members[0].path;
    keepPaths.add(keep);
    for (let i = 1; i < g.members.length; i++) {
      const member = g.members[i];
      if (member.path === keep || sourcePaths.has(member.path)) return null;
      sourcePaths.add(member.path);
      items.push({
        operation: 'quarantine',
        source: member.path,
        keep,
        expected_size: member.size,
      });
    }
  }
  if (items.length === 0 || [...sourcePaths].some(source => keepPaths.has(source))) return null;
  return items;
}

export function canCreatePathMatchPlan(
  preview: PathMatchPreviewResponse | null, activeKey: string | null,
  currentKey: string | null, busy: boolean,
): boolean {
  return !!preview && !!activeKey && activeKey === currentKey && !busy &&
    buildPathMatchPlanItems(preview, preview) !== null;
}
