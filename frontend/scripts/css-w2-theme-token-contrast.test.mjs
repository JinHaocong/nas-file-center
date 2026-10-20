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


test('Dashboard and Media real metric hover/normal paint evidence remains in Chromium CI', () => {
  const required = [
    'async function metricCardPaintSample(card, state)',
    "node.querySelector('.nfc-metric-' + role)",
    'getComputedStyle(target)',
    'style.backgroundColor',
    "style.backgroundImage !== 'none'",
    'Number(style.opacity) !== 1',
    'layers[layers.length - 1].alpha !== 1',
    "for (const state of ['normal', 'hover'])",
    "if (state === 'hover') await card.hover()",
    "node.matches(':hover')",
    'computedContrastRatio(role.foreground, role.background)',
    'await auditMetricHoverPaint(page, item, width, theme)',
    'metricHoverPaintAudit.length, WIDTHS.length * THEMES.length * 2 * 2 * 2',
    "writeFileSync(resolve(OUT, 'metric-hover-painted-contrast-audit.json')",
    'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []',
  ];
  for (const contract of required)
    assert.ok(browser.includes(contract), 'Actual metric hover contrast contract lost: ' + contract);
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  assert.ok(workflow.includes(
    'frontend/artifacts/browser-workspace-cascade/metric-hover-painted-contrast-audit.json'),
  'CI must upload actual rendered metric hover contrast evidence');
  assert.ok(browser.indexOf("path: resolve(OUT, item.id + '-' + label + '.png')") <
    browser.indexOf('await auditMetricHoverPaint(page, item, width, theme)'),
  'Pointer hover must happen after the accepted screenshot, never before it');
});


test('real DOM same-document workspace CSS theme inversion restores actual metric ink', () => {
  const required = [
    'async function auditLiveMetricThemeCascade(page, item, width, theme)',
    'async function metricThemeSnapshot(page, card)',
    "document.documentElement.dataset.theme = next",
    "document.documentElement.style.colorScheme = next",
    "document.documentElement.dataset.theme = before.effective",
    "document.documentElement.style.colorScheme = before.colorScheme",
    "storedMode: localStorage.getItem('nfc_theme_mode')",
    "metricCardPaintSample(card, 'normal')",
    'new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))',
    'await awaitPaintFlush();',
    'computedContrastRatio(role.foreground, role.background)',
    'assert.deepEqual(restored.tokens, initial.tokens',
    'assert.deepEqual(restored.contrasts.map(x => x.foreground)',
    'await auditLiveMetricThemeCascade(page, item, width, theme)',
    'liveMetricThemeAudit.length, WIDTHS.length * THEMES.length * 2',
    "writeFileSync(resolve(OUT, 'live-metric-theme-cascade-audit.json')",
    'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []',
  ];
  for (const invariant of required)
    assert.ok(browser.includes(invariant),
      'Same-document real CSS theme inversion audit removed: ' + invariant);
  assert.ok(browser.indexOf("path: resolve(OUT, item.id + '-' + label + '.png')") <
    browser.indexOf('await auditLiveMetricThemeCascade(page, item, width, theme)'),
    'Theme flip must only occur after accepted screenshots');
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  assert.ok(workflow.includes(
    'frontend/artifacts/browser-workspace-cascade/live-metric-theme-cascade-audit.json'),
    'Real browser theme inversion evidence must be uploaded in UI Validation');
  assert.ok(readFileSync('scripts/browser-theme-resilience.mjs', 'utf8')
    .includes("locator('#nfc-login-theme-select').selectOption('dark')"),
    'Actual ThemeProvider control test must be retained separately');
});


test('real authenticated ThemeProvider menu must update and restore painted metrics', () => {
  // A CSS-only data-theme flip cannot substitute for the actual Header menu,
  // React provider update and the persisted System/explicit theme preference.
  const guards = [
    'async function selectWorkspaceTheme(page, mode, effective)',
    'async function auditProviderMetricTheme(page, item, width, theme, motion = \'reduce\')',
    'summary[aria-label="切换界面主题"]',
    "page.getByRole('button', { name: '打开导航菜单' })",
    "page.getByRole('dialog', { name: 'NAS File Center 主导航' })",
    "dialog.getByRole('group', { name: '界面主题' })",
    "await dialog.waitFor({ state: 'hidden' })",
    "menu.getByRole('button', { name: providerModeLabels[mode] })",
    "localStorage.getItem('nfc_theme_mode') === mode",
    "selected?.textContent?.includes(label)",
    "await selectWorkspaceTheme(page, opposite, opposite)",
    "await selectWorkspaceTheme(page, theme.mode, theme.effective)",
    "changed = await metricThemeSnapshot(page, card)",
    "restored = await metricThemeSnapshot(page, card)",
    "assert.deepEqual(restored.tokens, initial.tokens",
    "initial.contrasts.map(x => [x.foreground, x.background])",
    'await auditProviderMetricTheme(page, item, width, theme)',
    'providerMetricThemeAudit.length, WIDTHS.length * THEMES.length * 2',
    "writeFileSync(resolve(OUT, 'provider-metric-theme-user-action-audit.json')",
    'item.changed.contrasts.every(role => role.contrast >= 4.5)',
    'item.restored.contrasts.every(role => role.contrast >= 4.5)',
    'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []',
  ];
  for (const invariant of guards)
    assert.ok(browser.includes(invariant),
      'Actual workspace ThemeProvider user action regression guard lost: ' + invariant);
  assert.ok(browser.indexOf("path: resolve(OUT, item.id + '-' + label + '.png')") <
    browser.indexOf('await auditProviderMetricTheme(page, item, width, theme)'),
    'Actual theme user action must not alter accepted screenshots');
  const mobileNav = readFileSync('src/components/Sidebar.tsx', 'utf8');
  const mobileCss = readFileSync('src/styles/console-v2-mobile-header.css', 'utf8');
  for (const invariant of ['nfc-v2-mobile-theme-switcher', 'aria-label="界面主题"',
    'aria-pressed={mode === key}', 'setMode(key); onNavigate?.()'])
    assert.ok(mobileNav.includes(invariant),
      'Mobile drawer must expose an actual accessible ThemeProvider user control: ' + invariant);
  for (const invariant of ['.nfc-v2-mobile-theme-options > button',
    'min-height: 44px', ':focus-visible'])
    assert.ok(mobileCss.includes(invariant),
      'Mobile theme choices must remain reachable with visible focus: ' + invariant);
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  assert.ok(workflow.includes(
    'frontend/artifacts/browser-workspace-cascade/provider-metric-theme-user-action-audit.json'),
  'CI must retain actual ThemeProvider workspace paint evidence as an artifact');
});


test('real ThemeProvider frame audits must catch intermediate painted metric contrast', () => {
  const invariants = [
    'async function armProviderMetricFrames(page, selector, expectedBefore, expectedAfter)',
    "observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] })",
    'requestAnimationFrame(collect)',
    'const PROVIDER_FRAME_COUNT = 12',
    "if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1)",
    "if (!layers.length || layers[layers.length - 1].alpha !== 1)",
    'getComputedStyle(target).color',
    'async function readProviderMetricFrames(page, expected, item, width, theme, phase)',
    'computedContrastRatio(role.foreground, role.background)',
    'assert.ok(ratio >= 4.5',
    "await armProviderMetricFrames(page, selector, theme.effective, opposite)",
    "await armProviderMetricFrames(page, selector, opposite, theme.effective)",
    "await readProviderMetricFrames(\n      page, opposite, item, width, theme, 'changed')",
    "await readProviderMetricFrames(\n      page, theme.effective, item, width, theme, 'restored')",
    'providerMetricFrameAudit.length, WIDTHS.length * THEMES.length * 2',
    "writeFileSync(resolve(OUT, 'provider-metric-theme-frame-audit.json')",
    'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []',
  ];
  for (const invariant of invariants) assert.ok(browser.includes(invariant),
    'Actual ThemeProvider per-frame painted contrast evidence lost: ' + invariant);
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  assert.ok(workflow.includes(
    'frontend/artifacts/browser-workspace-cascade/provider-metric-theme-frame-audit.json'),
  'CI must upload all captured ThemeProvider frame contrast evidence');
  assert.ok(browser.indexOf("path: resolve(OUT, item.id + '-' + label + '.png')") <
    browser.indexOf('await auditProviderMetricTheme(page, item, width, theme)'),
  'User theme animation sampling must not change accepted screenshot baselines');
});


test('v056 metric theme ink and surfaces never inherit legacy color/background transitions', () => {
  // index.css/v049 historically animated metric card background and value ink,
  // which can expose dark text on a new light card for a rendered frame.
  // Keep hover-only movement/shadow/border changes, not theme palette fades.
  const required = [
    '.nfc-app-main .nfc-metric-card {\n  transition-property: transform, box-shadow, border-color;',
    '.nfc-app-main .nfc-metric-label {\n  transition-property: none;',
    '.nfc-app-main .nfc-metric-value,\n.nfc-app-main .nfc-metric-icon {\n  transition-property: transform;',
  ];
  for (const declaration of required)
    assert.ok(css.includes(declaration),
      'Metric theme paint must not crossfade independently: ' + declaration);
  assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") >
    entry.indexOf("import './styles/v049-workspace.css';"),
    'Metric transition owner must follow historical CSS transitions');
});


test('normal-motion ThemeProvider frame acceptance stays independent from reduced motion', () => {
  const must = [
    'const NORMAL_MOTION_WIDTHS = new Set([360, 768, 1440])',
    "await page.emulateMedia({ reducedMotion: 'no-preference' })",
    "await auditProviderMetricTheme(page, item, width, theme, 'no-preference')",
    "await page.emulateMedia({ reducedMotion: 'reduce' })",
    "matchMedia('(prefers-reduced-motion: reduce)').matches",
    "'Normal motion must retain real hover and value motion: '",
    "'Normal motion must not silently inherit reduced-motion transition suppression'",
    "if (motion === 'no-preference') normalMotionMetricFrameAudit.push(evidence)",
    'normalMotionMetricFrameAudit.length,',
    "writeFileSync(resolve(OUT, 'provider-metric-theme-normal-motion-frame-audit.json')",
    'normalMotionContrastCount,',
    'frame.contrast >= 4.5',
    "assert.deepEqual(writes, []",
    "assert.deepEqual(outbound, []",
  ];
  for (const invariant of must) assert.ok(browser.includes(invariant),
    'Normal-motion real-user-frame regression guard lost: ' + invariant);
  assert.ok(browser.includes('const PROVIDER_FRAME_COUNT = 12'),
    'Normal motion must observe the same twelve first rendered frames');
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  assert.ok(workflow.includes(
    'frontend/artifacts/browser-workspace-cascade/provider-metric-theme-normal-motion-frame-audit.json'),
  'Normal-motion frame JSON evidence must be attached to the UI workflow');
  assert.ok(browser.indexOf("path: resolve(OUT, item.id + '-' + label + '.png')") <
    browser.indexOf("await auditProviderMetricTheme(page, item, width, theme, 'no-preference')"),
  'Normal-motion interactions must not alter the 352 accepted screenshot baselines');
});
