/**
 * v056 right-workspace semantic theme palette acceptance.
 * Checks source-declared opaque colors; not a human or browser sign-off.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
const entry = readFileSync('src/main.tsx', 'utf8');
const browser = readFileSync('scripts/browser-workspace-cascade.mjs', 'utf8');
function oneRoot(expression, name) {
  const blocks = [...css.matchAll(expression)];
  assert.equal(blocks.length, 1, 'Require one unconditional palette rule: ' + name);
  return blocks[0][1];
}
const light = oneRoot(/^:root\s*\{([^}]*)\}/gm, ':root');
const dark = oneRoot(/^\[data-theme='dark'\]\s*\{([^}]*)\}/gm, 'dark');
function token(block, role) {
  const name = '--nfc-w2-' + role;
  const matches = [...block.matchAll(new RegExp('(?:^|\\n)\\s*' + name +
    '\\s*:\\s*(#[0-9a-fA-F]{6})\\s*;', 'g'))];
  assert.equal(matches.length, 1, 'One opaque hex owner required: ' + name);
  return matches[0][1];
}
function luminance(hex) {
  const channels = [1, 3, 5].map(i => Number.parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(n => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4);
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
function contrast(foreground, background) {
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
const surfaces = ['canvas', 'surface', 'surface-soft', 'surface-strong'];
const textRoles = ['text', 'text-muted', 'text-subtle'];

test('v056 semantic color roles have paired explicit light/dark ownership', () => {
  const themed = [...surfaces, ...textRoles, 'accent', 'success', 'warning', 'danger'];
  for (const role of themed) {
    assert.notEqual(token(light, role).toLowerCase(), token(dark, role).toLowerCase(),
      'Theme colors must differ for ' + role);
  }
  // Dimension/radius tokens are intentionally inherited in dark mode.
  for (const role of ['radius-sm', 'radius-md', 'radius-lg', 'control',
    'content-max', 'workspace-max', 'panel-pad-x', 'panel-header-x']) {
    assert.ok(light.includes('--nfc-w2-' + role + ':'),
      'Missing independent layout token: ' + role);
  }
});

test('24 right-workspace text/surface pairs meet 4.5:1 on solid backgrounds', () => {
  let count = 0;
  for (const [mode, palette] of [['light', light], ['dark', dark]]) {
    const values = Object.fromEntries(textRoles.map(role => [role, token(palette, role)]));
    const tones = textRoles.map(role => luminance(values[role]));
    if (mode === 'light') assert.ok(tones[0] < tones[1] && tones[1] < tones[2],
      'Light text > muted > subtle visual hierarchy was lost');
    else assert.ok(tones[0] > tones[1] && tones[1] > tones[2],
      'Dark text > muted > subtle visual hierarchy was lost');
    for (const surface of surfaces) {
      const bg = token(palette, surface);
      for (const role of textRoles) {
        const actual = contrast(values[role], bg);
        assert.ok(actual >= 4.5, mode + ' ' + role + '/' + surface +
          ' contrasts only ' + actual.toFixed(2) + ':1, below 4.5:1');
        count++;
      }
    }
  }
  assert.equal(count, 24);
});

test('CSS import order, 8-width visual and system theme no-write evidence remain gated', () => {
  let previous = -1;
  for (const name of ['v049-workspace.css', 'v054-premium-system.css',
    'v055-workspace-breathing.css', 'v056-right-workspace-v2.css', 'console-v2.css']) {
    const index = entry.indexOf("import './styles/" + name + "';");
    assert.ok(index > previous, 'Missing or reordered CSS authority: ' + name);
    previous = index;
  }
  for (const invariant of ["request.method() !== 'GET'",
    'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
    "mode: 'system', system: 'dark', effective: 'dark'",
    '360, 390, 430, 768, 1024, 1280, 1440, 1920']) {
    assert.ok(browser.includes(invariant), 'Read-only browser evidence missing: ' + invariant);
  }
});


test('actual-route Chromium audit must cover all w2 computed semantic token pairings', () => {
  // Source-value contract above is not enough if a later sheet overrides the
  // inherited custom properties on a real routed workspace. Guard the browser
  // counterpart and its count/evidence against silent removal.
  const invariants = [
    'async function auditW2ComputedTheme(page, item, width, theme)',
    "const workspace = document.querySelector('.nfc-app-main')",
    'getComputedStyle(workspace)',
    "style.getPropertyValue('--nfc-w2-' + name)",
    'await auditW2ComputedTheme(page, item, width, theme)',
    'w2ThemeAudit.length, WIDTHS.length * THEMES.length * PAGES.length',
    "writeFileSync(resolve(OUT, 'w2-computed-theme-audit.json')",
    'w2ThemeAudit.length * 12',
    'ratio >= 4.5',
    'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []',
  ];
  for (const evidence of invariants) {
    assert.ok(browser.includes(evidence), 'Computed browser evidence removed: ' + evidence);
  }
  assert.ok(browser.includes("route: item.path, width, mode: theme.mode"),
    'Audited route/viewport/theme identity must be persisted');
  assert.ok(browser.includes("minimumContrast: Number(minimum.toFixed(3))"),
    'Persist numeric computed-token contrast evidence, not just pass/fail');
  const audit = readFileSync('scripts/browser-workspace-cascade.mjs', 'utf8');
  assert.ok(audit.includes('const PAGES = ['),
    'Real route inventory must be owned by the browser matrix');
});


test('real ledger headings must audit actual foreground and painted background', () => {
  const guards = [
    'async function auditPaintedLedgerHeading(page, item, width, theme)',
    "page.getByRole('heading', { name: item.heading, exact: true })",
    "element.closest('.nfc-app-main')",
    'getComputedStyle(element)',
    'textStyle.color',
    'getComputedStyle(node)',
    'style.backgroundColor',
    "style.backgroundImage !== 'none'",
    'Number(style.opacity) !== 1',
    'layers[layers.length - 1].alpha !== 1',
    'computedContrastRatio(rendered.foreground, rendered.paintedBackground)',
    'await auditPaintedLedgerHeading(page, item, width, theme)',
    'paintedHeadingAudit.length, WIDTHS.length * THEMES.length * (PAGES.length - 1)',
    "writeFileSync(resolve(OUT, 'painted-ledger-heading-audit.json')",
    'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []',
  ];
  for (const value of guards) {
    assert.ok(browser.includes(value),
      'Real painted ledger-heading contrast evidence removed: ' + value);
  }
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  for (const artifact of ['w2-computed-theme-audit.json',
    'painted-ledger-heading-audit.json', 'checkbox-keyboard-audit.json']) {
    assert.ok(workflow.includes('frontend/artifacts/browser-workspace-cascade/' + artifact),
      'Browser JSON evidence must actually upload to CI artifacts: ' + artifact);
  }
});
