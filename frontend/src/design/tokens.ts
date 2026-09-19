export const nfcTheme = {
  fontFamily:
    '"SF Pro Text", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  fontFamilyDisplay:
    '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, sans-serif',
  fontFamilyMono:
    '"SFMono-Regular", "Cascadia Code", "Roboto Mono", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
  light: {
    accent: '#335CFF',
    accentSoft: '#EEF1FF',
    canvas: '#F3F5F8',
    surface1: '#FFFFFF',
    surface2: '#F1F3F7',
    surfaceRaised: '#FFFFFF',
    navSurface: '#F8FAFC',
    hairline: '#E1E5EC',
    hairlineStrong: '#C9D0DA',
    text: '#15181D',
    textMuted: '#5D6673',
    textSubtle: '#87909D',
  },
  dark: {
    accent: '#8D98FF',
    accentSoft: '#1A2042',
    canvas: '#0B0E12',
    surface1: '#12161B',
    surface2: '#191E25',
    surfaceRaised: '#1B2028',
    navSurface: '#10151A',
    hairline: '#29313A',
    hairlineStrong: '#3B4652',
    text: '#F2F5F7',
    textMuted: '#AFB8C3',
    textSubtle: '#7F8A98',
  },
} as const;

export const nfcBreakpoints = {
  mobileMax: 767,
  tabletMin: 768,
  tabletMax: 1199,
  desktopMin: 1200,
} as const;
