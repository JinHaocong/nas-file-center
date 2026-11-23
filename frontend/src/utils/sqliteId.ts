const maxSqliteId = '9223372036854775807';

/** Check an exact positive SQLite row ID using decimal strings. */
export function isSqliteId(id: string): boolean {
  return /^[1-9]\d{0,18}$/.test(id) && (id.length < maxSqliteId.length || id <= maxSqliteId);
}
