import type { FilenameAuditPreview, FilenameAuditRow, FilenameIssue } from '../api/domain';

export type FilenameAuditFilterMode = 'all' | 'fixable' | FilenameIssue;
export type FilenameAuditRequest = { parent: string };
export type FilenameAuditPlanItem = { operation: 'rename'; source: string; target: string };

/** Preserve the literal directory parameter. Path normalization and permission are server authority. */
export function buildFilenameAuditRequest(parent: string): FilenameAuditRequest | null {
  return typeof parent === 'string' && parent.trim().length > 0 ? { parent } : null;
}

export function filterFilenameAuditRows(
  rows: readonly FilenameAuditRow[], filter: FilenameAuditFilterMode,
): FilenameAuditRow[] {
  if (filter === 'all') return [...rows];
  if (filter === 'fixable') return rows.filter(isFilenameAuditRepairable);
  return rows.filter(row => row.issues.includes(filter));
}

/** The backend alone issues suggestions; the UI only rejects obviously unsafe candidates. */
export function isFilenameAuditRepairable(row: FilenameAuditRow): boolean {
  return row.issues.includes('edge_whitespace') &&
    typeof row.suggested_target === 'string' &&
    row.suggested_target.length > 0 &&
    row.suggested_target !== row.path &&
    !row.suggestion_block_reason;
}

/**
 * Fail closed if any selected proposal was removed, changed, duplicated, or has a
 * conflicting target in the newest server report. Never derive target paths in UI.
 */
export function buildFilenameAuditPlanItems(
  preview: FilenameAuditPreview,
  fresh: FilenameAuditPreview,
  selectedPaths: readonly string[],
): FilenameAuditPlanItem[] | null {
  if (selectedPaths.length === 0 || preview.parent !== fresh.parent) return null;
  const original = new Map(preview.items.map(row => [row.path, row]));
  const latest = new Map(fresh.items.map(row => [row.path, row]));
  if (original.size !== preview.items.length || latest.size !== fresh.items.length) return null;
  const uniqueSources = new Set<string>();
  const uniqueTargets = new Set<string>();
  const items: FilenameAuditPlanItem[] = [];

  for (const path of selectedPaths) {
    if (uniqueSources.has(path)) return null;
    uniqueSources.add(path);
    const before = original.get(path);
    const after = latest.get(path);
    if (!before || !after || !isFilenameAuditRepairable(before) ||
        !isFilenameAuditRepairable(after) ||
        before.suggested_target !== after.suggested_target ||
        before.suggestion_block_reason !== after.suggestion_block_reason ||
        before.name !== after.name ||
        before.issues.length !== after.issues.length ||
        before.issues.some((issue, index) => issue !== after.issues[index])) return null;
    const target = after.suggested_target;
    if (!target || uniqueTargets.has(target) || uniqueSources.has(target)) return null;
    uniqueTargets.add(target);
    items.push({ operation: 'rename', source: path, target });
  }
  // Also reject if a target of a preceding item was selected as a later source.
  if (items.some(item => uniqueSources.has(item.target))) return null;
  return items;
}

export function canCreateFilenameAuditPlan(
  preview: FilenameAuditPreview | null,
  previewKey: string | null,
  selectedPaths: readonly string[],
  busy: boolean,
): boolean {
  return !busy && !!previewKey && !!preview &&
    buildFilenameAuditPlanItems(preview, preview, selectedPaths) !== null;
}

function csvValue(value: string | number | null | undefined): string {
  let valueText = String(value ?? '');
  // Spreadsheet formula neutralization applies even after leading whitespace.
  if (/^\s*[=+\-@]/.test(valueText)) valueText = "'" + valueText;
  return '"' + valueText.replace(/"/g, '""') + '"';
}

/** CSV export includes only filtered rows and never initiates a NAS mutation. */
export function buildFilenameAuditCsv(rows: readonly FilenameAuditRow[]): string {
  const data = [
    ['filename', 'absolute_path', 'issue_codes', 'suggested_target', 'block_reason'],
    ...rows.map(row => [row.name, row.path, row.issues.join(';'),
      row.suggested_target || '', row.suggestion_block_reason || '']),
  ];
  return '\uFEFF' + data.map(row => row.map(csvValue).join(',')).join('\r\n');
}
