/**
 * Strict CSS computed colors used by the isolated Chromium paint audit.
 * Only RGB/sRGB and numeric Oklab are modeled. Out-of-gamut Oklab is
 * rejected instead of pretending channel clipping is CSS gamut mapping.
 * All RGB channels are gamma-encoded 0..255 floats, not rounded pixels.
 */
const NUMBER = String.raw`[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?`;
const OKLAB = new RegExp('^oklab\\(\\s*(' + NUMBER + ')\\s+(' + NUMBER +
  ')\\s+(' + NUMBER + ')(?:\\s*\\/\\s*(' + NUMBER + '))?\\s*\\)$');
const RGB = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(\d*\.?\d+))?\s*\)$/;
const SRGB = new RegExp('^color\\(srgb\\s+(' + NUMBER + ')\\s+(' + NUMBER +
  ')\\s+(' + NUMBER + ')(?:\\s*\\/\\s*(' + NUMBER + '))?\\s*\\)$');

export function parseComputedPaintColor(value) {
  if (typeof value !== 'string') throw new TypeError('Computed paint must be text');
  const matchRgb = RGB.exec(value);
  const matchSrgb = !matchRgb && SRGB.exec(value);
  const matchLab = !matchRgb && !matchSrgb && OKLAB.exec(value);
  const matched = matchRgb || matchSrgb || matchLab;
  if (!matched) throw new TypeError('Unsupported computed Tasks error color: ' + value);
  const [c1, c2, c3] = matched.slice(1, 4).map(Number);
  const alpha = matched[4] === undefined ? 1 : Number(matched[4]);
  if (![c1, c2, c3, alpha].every(Number.isFinite) || alpha < 0 || alpha > 1)
    throw new RangeError('Invalid computed Tasks paint channels/alpha: ' + value);

  if (matchRgb) {
    if ([c1, c2, c3].some(v => v < 0 || v > 255))
      throw new RangeError('Out-of-range computed RGB paint: ' + value);
    return { channels: [c1, c2, c3], alpha };
  }
  if (matchSrgb) {
    if ([c1, c2, c3].some(v => v < 0 || v > 1))
      throw new RangeError('Out-of-gamut computed sRGB paint: ' + value);
    return { channels: [c1, c2, c3].map(v => v * 255), alpha };
  }
  // Even an out-of-gamut chromatic color contributes exactly zero paint at
  // alpha=0. Do not accept any OTHER unknown color syntax as "transparent".
  if (alpha === 0) return { channels: [0, 0, 0], alpha: 0 };
  const L = c1, a = c2, b = c3;
  if (L < 0 || L > 1 || Math.abs(a) > 0.5 || Math.abs(b) > 0.5)
    throw new RangeError('Out-of-range computed Oklab paint: ' + value);
  // Björn Ottosson's Oklab -> linear-light sRGB inverse.
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  const linear = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ];
  // Minor 1e-5 errors occur near pure black/white due to published matrix
  // precision. Anything materially out-of-gamut fails rather than being
  // silently clipped and falsely certified against the rendered surface.
  if (linear.some(v => !Number.isFinite(v) || v < -1e-5 || v > 1 + 1e-5))
    throw new RangeError('Out-of-gamut Oklab requires rendered pixel audit: ' + value);
  const channels = linear.map(v => {
    const clamped = Math.max(0, Math.min(1, v));
    const srgb = clamped <= 0.0031308
      ? clamped * 12.92
      : 1.055 * clamped ** (1 / 2.4) - 0.055;
    return srgb * 255;
  });
  return { channels, alpha };
}

export function contrastRatioForOpaqueChannels(foreground, background) {
  const luminance = channels => {
    if (!Array.isArray(channels) || channels.length !== 3 ||
        channels.some(v => !Number.isFinite(v) || v < 0 || v > 255))
      throw new RangeError('Contrast requires three finite, in-gamut RGB channels');
    const linear = channels.map(value => {
      const srgb = value / 255;
      return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
    });
    return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  };
  const [a, b] = [luminance(foreground), luminance(background)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}
