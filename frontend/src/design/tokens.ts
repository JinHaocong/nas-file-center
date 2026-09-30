export const nfcTheme = {
  fontFamily:
    '"SF Pro Text", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  fontFamilyDisplay:
    '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, sans-serif',
  fontFamilyMono:
    '"SFMono-Regular", "Cascadia Code", "Roboto Mono", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
  light: {
    accent: '#1769E0',
    accentSoft: '#E9F1FF',
    canvas: '#F5F6F8',
    surface1: '#FFFFFF',
    surface2: '#F0F2F5',
    surfaceRaised: '#FFFFFF',
    navSurface: '#F8FAFC',
    hairline: '#E1E4E8',
    hairlineStrong: '#C9CED6',
    text: '#17191D',
    textMuted: '#5F6670',
    textSubtle: '#8A919B',
  },
  dark: {
    accent: '#64A7FF',
    accentSoft: '#13263E',
    canvas: '#0C0F13',
    surface1: '#12161B',
    surface2: '#191E24',
    surfaceRaised: '#1B2027',
    navSurface: '#101419',
    hairline: '#293039',
    hairlineStrong: '#3A444F',
    text: '#F0F3F6',
    textMuted: '#AEB6C0',
    textSubtle: '#7E8894',
  },
} as const;

export const nfcBreakpoints = {
  mobileMax: 767,
  tabletMin: 768,
  tabletMax: 1199,
  desktopMin: 1200,
} as const;
