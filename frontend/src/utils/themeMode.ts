/**
 * Theme preference normalization and effective dark-mode selection.
 * Kept browser-independent so persisted invalid values fail back to the
 * established light default, and system preference only affects system mode.
 */
export type ThemeMode = 'light' | 'dark' | 'system';

export function normalizeThemeMode(value: unknown): ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'light';
}

export function shouldUseDarkTheme(mode: ThemeMode, systemDark: boolean): boolean {
  return mode === 'dark' || (mode === 'system' && systemDark);
}
