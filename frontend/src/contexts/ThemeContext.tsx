import React, { createContext, useContext, useEffect, useState } from 'react';
import { restoreThemeMode, persistThemeMode, shouldUseDarkTheme, syncThemeModeFromStorage, readSystemDarkPreference, watchSystemDarkPreference, type ThemeMode } from '../utils/themeMode';

// Preserve the public type contract for Login, Settings, and shell consumers.
export type { ThemeMode } from '../utils/themeMode';

interface ThemeContextType {
  mode: ThemeMode;
  isDark: boolean;
  setMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextType>({
  mode: 'system',
  isDark: false,
  setMode: () => {},
});

/**
 * Native theme context. Design tokens belong to existing :root and
 * [data-theme='dark'] CSS declarations, not a component-library-specific JavaScript provider.
 */
const systemColorSchemeQuery = () => window.matchMedia?.('(prefers-color-scheme: dark)');

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setModeState] = useState<ThemeMode>(() =>
    restoreThemeMode(() => localStorage.getItem('nfc_theme_mode')),
  );
  const [systemDark, setSystemDark] = useState(() =>
    readSystemDarkPreference(systemColorSchemeQuery),
  );

  useEffect(() => watchSystemDarkPreference(systemColorSchemeQuery, setSystemDark), []);

  // Theme preferences are shared between tabs. StorageEvent does not fire
  // in the tab that made the change, and events from sessionStorage must not
  // overwrite the current selection. Accessing localStorage may itself throw.
  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      try {
        if (event.storageArea !== window.localStorage) return;
      } catch {
        return;
      }
      setModeState(current => syncThemeModeFromStorage(current, event.key, event.newValue));
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const setMode = (newMode: ThemeMode) => {
    setModeState(newMode);
    persistThemeMode(() => localStorage.setItem('nfc_theme_mode', newMode));
  };

  const isDark = shouldUseDarkTheme(mode, systemDark);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
  }, [isDark]);

  return (
    <ThemeContext.Provider value={{ mode, isDark, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);
