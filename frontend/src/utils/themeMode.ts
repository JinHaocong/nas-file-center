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

/**
 * Browser media APIs may be unavailable or reject queries in restricted
 * contexts. Fall back to the established light system preference in that case;
 * explicit light/dark selections are unaffected.
 */
export function readSystemDarkPreference(
  query: () => MediaQueryList | null | undefined,
): boolean {
  try {
    return Boolean(query()?.matches);
  } catch {
    return false;
  }
}

/**
 * Observe OS scheme changes without assuming modern MediaQueryList events.
 * The effect re-reads the current value to cover changes between render and
 * subscription. Return an idempotent cleanup even when APIs are blocked.
 */
export function watchSystemDarkPreference(
  query: () => MediaQueryList | null | undefined,
  onChange: (dark: boolean) => void,
): () => void {
  let media: MediaQueryList | null | undefined;
  try {
    media = query();
    if (!media) return () => {};
    onChange(Boolean(media.matches));
  } catch {
    return () => {};
  }

  const handleChange = (event: MediaQueryListEvent) => onChange(Boolean(event.matches));
  try {
    media.addEventListener('change', handleChange);
    return () => {
      try { media.removeEventListener('change', handleChange); } catch { /* blocked */ }
    };
  } catch {
    // Legacy WebKit MediaQueryList supported addListener/removeListener only.
    try {
      media.addListener(handleChange);
      return () => {
        try { media.removeListener(handleChange); } catch { /* blocked */ }
      };
    } catch {
      return () => {};
    }
  }
}
