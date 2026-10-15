/**
 * Shared deterministic *synthetic* browser fixtures, never real NAS state.
 * Callers independently reject off-origin and all unapproved write requests.
 */
export const VISUAL_FIXTURE_TIMESTAMP = '2026-10-12T08:30:00Z';
export function visualAdminFixture(username) {
  return { id: 1, username, role: 'admin', is_admin: true };
}
export function visualSafeSettingsFixture() {
  return { allow_mutation: false, allow_delete: false, safe_mode: true };
}
export const visualViewports = Object.freeze([360, 390, 430, 768, 1024, 1280, 1440, 1920]);
export const visualThemes = Object.freeze([
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
]);

/**
 * GET-only directory payload for the Archive Recovery visual browser suites.
 * "Other" folders are empty; no fixture ever reads the real NAS filesystem.
 * Only a synthetic archive basename is supplied by each scenario.
 */
export function visualArchiveDirectoryFixture(path, archiveName = 'fixture.zip') {
  const items = path === '/data' ? [{
    name: archiveName, path: '/data/' + archiveName,
    type: 'file', is_dir: false, size: 123,
  }] : [];
  return {
    path, parent: null, allowed_roots: ['/data'], items,
    total: items.length, page: 1, page_size: 100, has_more: false,
  };
}
