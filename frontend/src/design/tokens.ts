export const nfcTheme = {
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  light: {
    accent: '#335cff',
    canvas: '#f6f7f9',
    surface1: '#ffffff',
    surface2: '#f1f3f6',
    surfaceRaised: '#ffffff',
    hairline: '#e4e7ec',
    hairlineStrong: '#c9ced8',
    text: '#17191c',
    textMuted: '#5f6672',
    textSubtle: '#858c98',
  },
  dark: {
    accent: '#7f8cff',
    canvas: '#0d0f12',
    surface1: '#13161a',
    surface2: '#191d22',
    surfaceRaised: '#1d2228',
    hairline: '#282d34',
    hairlineStrong: '#3a414b',
    text: '#f3f5f7',
    textMuted: '#b4bac3',
    textSubtle: '#858d99',
  },
} as const;

export const nfcBreakpoints = {
  mobileMax: 767,
  tabletMin: 768,
  tabletMax: 1199,
  desktopMin: 1200,
} as const;
