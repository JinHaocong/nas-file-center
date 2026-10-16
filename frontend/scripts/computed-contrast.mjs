/** WCAG 2.x luminance ratio for opaque colors returned by Chromium getComputedStyle().
 * Invalid or translucent values fail closed: comparing them without compositing would
 * falsely certify a focus indicator against an unknown underlying surface.
 */
export function computedContrastRatio(foreground, background) {
  const luminance = value => {
    const match = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(value);
    if (!match || (match[4] !== undefined && Number(match[4]) !== 1)) {
      throw new TypeError('Expected opaque computed RGB color, received: ' + value);
    }
    const channels = match.slice(1, 4).map(Number);
    if (channels.some(value => value > 255)) {
      throw new RangeError('Computed RGB channel exceeds 255: ' + value);
    }
    const [r, g, b] = channels.map(channel => {
      const srgb = channel / 255;
      return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
    });
    return r * 0.2126 + g * 0.7152 + b * 0.0722;
  };
  const [lighter, darker] = [luminance(foreground), luminance(background)]
    .sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}
