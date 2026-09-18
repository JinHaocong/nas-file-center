export const nfcTheme = {
  fontFamily:
    '"SF Pro Text", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  fontFamilyDisplay:
    '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, sans-serif',
  fontFamilyMono:
    '"SFMono-Regular", "Cascadia Code", "Roboto Mono", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
  light: {
    accent: '#0A84FF',
    accentSoft: '#EAF3FF',
    canvas: '#F6F7F9',
    surface1: '#FFFFFF',
    surface2: '#F2F4F7',
    surfaceRaised: '#FFFFFF',
    navSurface: '#FBFCFE',
    hairline: '#E6E8EC',
    hairlineStrong: '#D2D6DC',
    text: '#101114',
    textMuted: '#5E6470',
    textSubtle: '#8C929D',
  },
  dark: {
    accent: '#4DA3FF',
    accentSoft: '#10243A',
    canvas: '#0C0D10',
    surface1: '#121418',
    surface2: '#181B20',
    surfaceRaised: '#1A1D22',
    navSurface: '#111318',
    hairline: '#252A31',
    hairlineStrong: '#363D47',
    text: '#F5F7FA',
    textMuted: '#AAB0BA',
    textSubtle: '#747C88',
  },
} as const;

export const nfcBreakpoints = {
  mobileMax: 767,
  tabletMin: 768,
  tabletMax: 1199,
  desktopMin: 1200,
} as const;
