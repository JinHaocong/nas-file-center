import test from 'node:test';
import assert from 'node:assert/strict';
import { parseComputedPaintColor, contrastRatioForOpaqueChannels } from './computed-paint-color.mjs';

const near = (actual, expected, epsilon = 0.2) =>
  assert.ok(Math.abs(actual - expected) <= epsilon,
    'Expected channel ' + expected + ', received ' + actual);

test('computed numeric Oklab converts actual Chromium hover surface to finite sRGB', () => {
  const paint = parseComputedPaintColor('oklab(0.981766 -0.000276804 0.00111037)');
  assert.equal(paint.alpha, 1);
  assert.equal(paint.channels.length, 3);
  assert.ok(paint.channels.every(channel => Number.isFinite(channel) &&
    channel >= 0 && channel <= 255));
  assert.ok(paint.channels.every(channel => channel > 230));
});

test('Oklab conversion agrees with canonical black, white, red and blue references', () => {
  for (const [value, expected] of [
    ['oklab(0 0 0)', [0, 0, 0]],
    ['oklab(1 0 0)', [255, 255, 255]],
    ['oklab(0.6279553606145516 0.22486306106597398 0.1258462985307351)', [255, 0, 0]],
    ['oklab(0.4520137183853429 -0.03245698416876397 -0.3115281476783751)', [0, 0, 255]],
  ]) {
    const actual = parseComputedPaintColor(value);
    expected.forEach((channel, i) => near(actual.channels[i], channel));
  }
});

test('alpha only blends modeled colors; exact transparent Oklab contributes nothing', () => {
  assert.deepEqual(parseComputedPaintColor('oklab(0 0 0 / 0)'),
    { channels: [0, 0, 0], alpha: 0 });
  assert.deepEqual(parseComputedPaintColor('oklab(0.981766 -0.000276804 0.00111037 / 0)'),
    { channels: [0, 0, 0], alpha: 0 });
  const translucent = parseComputedPaintColor('oklab(0.6 0 0 / 0.5)');
  assert.equal(translucent.alpha, 0.5);
  assert.ok(translucent.channels.every(channel => channel > 0 && channel < 255));
});

test('RGB/sRGB and floating WCAG contrast retain opaque numeric precision', () => {
  assert.deepEqual(parseComputedPaintColor('rgb(255, 255, 255)'),
    { channels: [255, 255, 255], alpha: 1 });
  assert.deepEqual(parseComputedPaintColor('rgba(0, 0, 0, 0)'),
    { channels: [0, 0, 0], alpha: 0 });
  assert.deepEqual(parseComputedPaintColor('color(srgb 1 0 0 / 0.5)'),
    { channels: [255, 0, 0], alpha: 0.5 });
  assert.equal(contrastRatioForOpaqueChannels([255, 255, 255], [0, 0, 0]), 21);
  near(contrastRatioForOpaqueChannels([100.2, 100.3, 100.4],
    [250.4, 250.2, 250]), 5.61, 0.4);
});

test('gamut overflow, unknown color syntax and invalid alpha fail closed', () => {
  for (const value of [
    'oklab(0.5 0.5 0.5)',
    'oklab(1.4 0 0)',
    'oklab(0.6 0.2 -0.9)',
    'oklab(0.6 0 0 / 1.5)',
    'oklab(0.6 0 0 / -0.1)',
    'oklab(0.6 none 0)',
    'oklch(0.6 0.1 20)',
    'color(display-p3 1 0 0)',
    'color(srgb 1.2 0 0)',
    'rgb(300, 0, 0)',
    'transparent',
    'var(--v2-paper)',
  ]) assert.throws(() => parseComputedPaintColor(value), undefined,
    'Unsafe/unmodeled CSS paint must be refused: ' + value);
  assert.throws(() => contrastRatioForOpaqueChannels([256, 0, 0], [0, 0, 0]));
});
