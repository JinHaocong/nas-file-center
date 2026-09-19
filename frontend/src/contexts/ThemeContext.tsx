import React, { createContext, useContext, useEffect, useState } from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { nfcTheme } from '../design/tokens';

export type ThemeMode = 'light' | 'dark' | 'system';

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

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem('nfc_theme_mode') as ThemeMode;
    return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : 'system';
  });

  const [systemDark, setSystemDark] = useState(() => {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (e: MediaQueryListEvent) => {
      setSystemDark(e.matches);
    };
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  const setMode = (newMode: ThemeMode) => {
    setModeState(newMode);
    localStorage.setItem('nfc_theme_mode', newMode);
  };

  const isDark = mode === 'dark' || (mode === 'system' && systemDark);
  const palette = isDark ? nfcTheme.dark : nfcTheme.light;

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
  }, [isDark]);

  return (
    <ThemeContext.Provider value={{ mode, isDark, setMode }}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: palette.accent,
            colorBgLayout: palette.canvas,
            colorBgContainer: palette.surface1,
            colorBgElevated: palette.surfaceRaised,
            colorBorderSecondary: palette.hairline,
            colorText: palette.text,
            colorTextSecondary: palette.textMuted,
            borderRadius: 8,
            borderRadiusLG: 12,
            controlHeight: 36,
            controlHeightLG: 40,
            fontSize: 14,
            fontFamily: nfcTheme.fontFamily,
          },
          components: {
            Button: {
              fontWeight: 560,
              defaultShadow: 'none',
              primaryShadow: 'none',
              dangerShadow: 'none',
            },
            Input: {
              activeBorderColor: palette.accent,
              hoverBorderColor: palette.hairlineStrong,
              activeShadow: 'none',
            },
            Select: {
              activeBorderColor: palette.accent,
              hoverBorderColor: palette.hairlineStrong,
              activeOutlineColor: 'transparent',
            },
            Table: {
              headerBg: palette.surface2,
              headerColor: palette.textSubtle,
              rowHoverBg: palette.surface2,
              borderColor: palette.hairline,
              cellPaddingBlock: 9,
              cellPaddingInline: 11,
            },
            Modal: {
              contentBg: palette.surfaceRaised,
              headerBg: 'transparent',
              titleColor: palette.text,
            },
            Drawer: {
              colorBgElevated: palette.surfaceRaised,
            },
            Dropdown: {
              colorBgElevated: palette.surfaceRaised,
              controlItemBgHover: palette.surface2,
            },
            Card: {
              colorBgContainer: palette.surface1,
              headerBg: 'transparent',
            },
            Tabs: {
              itemSelectedColor: palette.text,
              itemHoverColor: palette.accent,
              inkBarColor: palette.accent,
            },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);
