import React, { createContext, useContext, useEffect, useState } from 'react';
import { normalizeThemeMode, shouldUseDarkTheme, type ThemeMode } from '../utils/themeMode';

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
 * [data-theme='dark'] CSS declarations, not an AntD ConfigProvider.
 */
export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setModeState] = useState<ThemeMode>(() =>
    normalizeThemeMode(localStorage.getItem('nfc_theme_mode')),
  );
  const [systemDark, setSystemDark] = useState(() =>
    Boolean(window.matchMedia?.('(prefers-color-scheme: dark)').matches),
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mediaQuery) return;
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  const setMode = (newMode: ThemeMode) => {
    setModeState(newMode);
    localStorage.setItem('nfc_theme_mode', newMode);
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
