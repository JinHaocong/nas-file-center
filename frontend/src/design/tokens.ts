export const nfcTheme = {
  fontFamily:
    '"SF Pro Text", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif',
  fontFamilyDisplay:
    '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", sans-serif',
  fontFamilyMono:
    '"SFMono-Regular", "Cascadia Code", "Roboto Mono", ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
  light: {
    accent: '#167a5c',
    canvas: '#f4f6f5',
    surface1: '#fbfcfc',
    surface2: '#eef1f0',
    surfaceRaised: '#ffffff',
    hairline: '#dde2df',
    hairlineStrong: '#c4ccc8',
    text: '#111513',
    textMuted: '#5d6762',
    textSubtle: '#87908c',
  },
  dark: {
    accent: '#4fd1a1',
    canvas: '#0a0d0c',
    surface1: '#101412',
    surface2: '#171c1a',
    surfaceRaised: '#1b211e',
    hairline: '#252c29',
    hairlineStrong: '#39433f',
    text: '#f3f7f5',
    textMuted: '#afb9b4',
    textSubtle: '#7d8883',
  },
} as const;

export const nfcBreakpoints = {
  mobileMax: 767,
  tabletMin: 768,
  tabletMax: 1199,
  desktopMin: 1200,
} as const;
