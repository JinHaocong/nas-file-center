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
