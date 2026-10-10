/** Native editor adapters; persisted workflow values and backend checks remain authoritative. */
export const MAX_SCAN_ROOTS = 16;
export function selectOrganizerRoot(current: readonly number[], id: number, available: readonly number[]): number[] {
  return Number.isSafeInteger(id) && id > 0 && available.includes(id) ? [id] : [...current];
}
export function toggleScanRoot(current: readonly number[], id: number, checked: boolean, available: readonly number[]): number[] {
  if (!Number.isSafeInteger(id) || id <= 0) return [...current];
  if (!checked) return current.filter(root => root !== id);
  if (!available.includes(id) || current.includes(id) || current.length >= MAX_SCAN_ROOTS) return [...current];
  return [...current, id];
}
/** Preserve saved roots not present in the first page or during an API error. */
export function mergeMissingRootIds(available: readonly number[], selected: readonly number[]): number[] {
  return [...new Set([...available, ...selected])];
}
export function scanSubpathValue(value: string): string | undefined { return value.trim() || undefined; }
export function moveSubpathValue(value: string): string { return value.trim(); }
const pad = (n: number, size = 2) => String(n).padStart(size, '0');
export function formatTouchTimeLocal(mtimeNs: number | null): string {
  if (!mtimeNs || !Number.isFinite(mtimeNs)) return '';
  const d = new Date(mtimeNs / 1_000_000);
  if (Number.isNaN(d.getTime())) return '';
  return [pad(d.getFullYear(), 4), '-', pad(d.getMonth()+1), '-', pad(d.getDate()),
    'T', pad(d.getHours()), ':', pad(d.getMinutes()), ':', pad(d.getSeconds()), '.', pad(d.getMilliseconds(), 3)].join('');
}
/** Reject invalid local dates instead of normalizing a DST gap or impossible day. */
export function parseTouchTimeLocal(value: string): number | null {
  if (!value) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(value);
  if (!m) return null;
  const year = Number(m[1]), month = Number(m[2]), day = Number(m[3]);
  const hour = Number(m[4]), minute = Number(m[5]), second = Number(m[6] || 0);
  const ms = Number((m[7] || '').padEnd(3, '0'));
  if (year < 100 || month < 1 || month > 12 || day < 1 || day > 31 ||
      hour > 23 || minute > 59 || second > 59) return null;
  const date = new Date(year, month - 1, day, hour, minute, second, ms);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day ||
      date.getHours() !== hour || date.getMinutes() !== minute ||
      date.getSeconds() !== second || date.getMilliseconds() !== ms) return null;
  return date.getTime() * 1_000_000;
}
