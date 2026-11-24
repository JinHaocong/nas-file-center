const maxSqliteId = '9223372036854775807';

/** Check an exact positive SQLite row ID using decimal strings. */
export function isSqliteId(id: string): boolean {
  return /^[1-9]\d{0,18}$/.test(id) && (id.length < maxSqliteId.length || id <= maxSqliteId);
}

/** Preserve decimal string IDs and reject imprecise legacy numeric IDs. */
export function sqliteIdText(value: unknown): string | null {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) return String(value);
  return typeof value === 'string' && isSqliteId(value) ? value : null;
}
