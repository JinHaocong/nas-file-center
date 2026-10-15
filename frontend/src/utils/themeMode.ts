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

/**
 * Browser storage can throw SecurityError in restricted/embed contexts.
 * Prefer the established light fallback to crashing the entire shell.
 */
export function restoreThemeMode(read: () => unknown): ThemeMode {
  try {
    return normalizeThemeMode(read());
  } catch {
    return 'light';
  }
}

/** Persist when possible without undoing a valid in-session theme choice. */
export function persistThemeMode(write: () => void): void {
  try {
    write();
  } catch {
    // Storage may be blocked or full; the React state remains authoritative.
  }
}

/**
 * A StorageEvent is fired in *other* tabs, not in the tab that wrote
 * nfc_theme_mode. Treat removal and clear() as the established light default;
 * never let unrelated keys reset the user's in-session selection.
 * The provider checks storageArea before calling this reducer.
 */
export function syncThemeModeFromStorage(
  current: ThemeMode,
  key: string | null,
  newValue: unknown,
): ThemeMode {
  if (key !== null && key !== 'nfc_theme_mode') return current;
  return normalizeThemeMode(newValue);
}
