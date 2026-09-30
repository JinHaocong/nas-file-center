export const nfcTheme = {
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  fontFamilyDisplay:
    '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  fontFamilyMono:
    '"SFMono-Regular", "Cascadia Code", "Roboto Mono", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
  light: {
    accent: '#4361EE',
    accentSoft: '#EEF2FF',
    canvas: '#F5F6F8',
    surface1: '#FFFFFF',
    surface2: '#F0F2F5',
    surfaceRaised: '#FFFFFF',
    navSurface: '#F8F9FB',
    hairline: '#E4E7EC',
    hairlineStrong: '#D2D7DF',
    text: '#20242C',
    textMuted: '#626B78',
    textSubtle: '#8A93A0',
  },
  dark: {
    accent: '#8EA2FF',
    accentSoft: '#202A52',
    canvas: '#0E1116',
    surface1: '#14181E',
    surface2: '#1A1F27',
    surfaceRaised: '#1E242D',
    navSurface: '#11151B',
    hairline: '#2A313B',
    hairlineStrong: '#3A4450',
    text: '#F2F4F7',
    textMuted: '#AEB6C2',
    textSubtle: '#7F8997',
  },
} as const;

export const nfcBreakpoints = {
  mobileMax: 767,
  tabletMin: 768,
  tabletMax: 1199,
  desktopMin: 1200,
} as const;
