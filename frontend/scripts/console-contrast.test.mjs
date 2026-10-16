/** Stage 5E-AK: enforce WCAG AA normal-text contrast for shared Pure White labels.
 * These source-declared CSS tokens drive both the React shell and Radix portals;
 * this intentionally does not claim every page has completed a human contrast audit.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const shell = readFileSync('src/styles/console-v2.css', 'utf8');
const overlays = readFileSync('src/styles/console-v2-task-overlays.css', 'utf8');
const canonical = readFileSync('src/styles/tokens.css', 'utf8');
const primitiveStyles = readFileSync('src/styles/primitives.css', 'utf8');
const v049Styles = readFileSync('src/styles/v049-workspace.css', 'utf8');

function rule(css, selector) {
  const index = css.indexOf(selector);
  assert.ok(index !== -1, 'Missing CSS selector: ' + selector);
  // Selectors supplied here end with '{'. The opening brace belongs to
  // this rule; searching *after* it would accidentally inspect the next rule.
  const opening = index + selector.length - 1;
  assert.equal(css[opening], '{', 'Selector must include its opening brace');
  const closing = css.indexOf('}', opening);
  assert.ok(closing > opening, 'Missing CSS rule body for ' + selector);
  return css.slice(opening + 1, closing);
}

function token(body, name) {
  const found = body.match(new RegExp('(?:^|\\n)\\s*' + name + '\\s*:\\s*(#[0-9a-fA-F]{6})\\s*;'));
  assert.ok(found, 'Missing solid hexadecimal token: ' + name);
  return found[1];
}

function luminance(hex) {
  const r = [1, 3, 5].map(i => Number.parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return r[0] * 0.2126 + r[1] * 0.7152 + r[2] * 0.0722;
}

function contrast(foreground, background) {
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function requireAA(label, foreground, backgrounds) {
  for (const [surface, background] of backgrounds) {
    const value = contrast(foreground, background);
    assert.ok(value >= 4.5,
      label + ' on ' + surface + ' only has ' + value.toFixed(2) + ':1; normal text requires 4.5:1');
  }
}

const shellLight = rule(shell, '.nfc-v2-shell {');
const shellDark = rule(shell, "[data-theme='dark'] .nfc-v2-shell {");
const portalLight = rule(overlays,
  '.nfc-v2-sheet, .nfc-v2-confirm-dialog, .nfc-v2-history-dialog {');
const portalDark = rule(overlays,
  "[data-theme='dark'] .nfc-v2-sheet,\n[data-theme='dark'] .nfc-v2-confirm-dialog,\n[data-theme='dark'] .nfc-v2-history-dialog {");

test('WCAG contrast formula uses sRGB linearization', () => {
  assert.equal(contrast('#000000', '#ffffff'), 21);
  assert.equal(contrast('#abcdef', '#abcdef'), 1);
  assert.ok(contrast('#858580', '#ffffff') < 4.5,
    'original Pure White subtle labels must not silently return');
});

test('canonical shared token palette matches shell and portal contrast in both themes', () => {
  const canonicalLight = rule(canonical, ':root {');
  const canonicalDark = rule(canonical, "[data-theme='dark'] {");
  for (const [mode, values, shellValues, portalValues] of [
    ['light', canonicalLight, shellLight, portalLight],
    ['dark', canonicalDark, shellDark, portalDark],
  ]) {
    const subtle = token(values, '--nfc-text-subtle');
    assert.equal(subtle, token(shellValues, '--v2-subtle'),
      mode + ' canonical and shell must not diverge');
    assert.equal(subtle, token(portalValues, '--v2-subtle'),
      mode + ' canonical and Radix portals must not diverge');

    const surfaceNames = ['--nfc-canvas', '--nfc-surface-1',
      '--nfc-surface-2', '--nfc-surface-raised', '--nfc-nav-surface',
      '--nfc-accent-soft'];
    requireAA(mode + ' canonical shared text', subtle,
      surfaceNames.map(name => [name, token(values, name)]));
  }
  assert.match(canonical, /--v2-subtle:\s*var\(--nfc-text-subtle\)/,
    'compatibility alias must inherit the canonical accessible value');
  assert.match(primitiveStyles, /\.nfc-page-eyebrow\s*\{[^}]*color:\s*var\(--nfc-text-subtle\)/);
  assert.match(primitiveStyles, /\.nfc-data-panel-description\s*\{[^}]*color:\s*var\(--nfc-text-subtle\)/);
  assert.match(primitiveStyles, /\.nfc-metric-label\s*\{[^}]*color:\s*var\(--nfc-text-subtle\)/);
  assert.match(v049Styles, /\\.nfc-page-eyebrow\\s*\\{\\s*color:\\s*var\\(--nfc-text-subtle\\)/,
    'later historical CSS must not replace canonical AA header color');
  assert.doesNotMatch(v049Styles, /\\.nfc-page-eyebrow\\s*\\{\\s*color:\\s*var\\(--nfc-v49-subtle\\)/);
  assert.match(readFileSync('src/styles/v047.css', 'utf8'), /@import '.\/tokens.css';/,
    'actual v047 import must keep the canonical tokens in the cascade');
});

test('light Pure White small secondary text passes AA on its actual light surfaces', () => {
  const foreground = token(shellLight, '--v2-subtle');
  requireAA('shell small secondary text', foreground, [
    ['canvas', token(shellLight, '--v2-canvas')],
    ['paper', token(shellLight, '--v2-paper')],
    ['sidebar', token(shellLight, '--v2-sidebar')],
    ['sidebar surface', token(shellLight, '--v2-sidebar-surface')],
    ['soft neutral surface', token(shellLight, '--v2-indigo-soft')],
  ]);
  requireAA('sidebar muted navigation text', token(shellLight, '--v2-sidebar-muted'), [
    ['sidebar', token(shellLight, '--v2-sidebar')],
    ['sidebar surface', token(shellLight, '--v2-sidebar-surface')],
  ]);
  assert.match(shell, /\.nfc-v2-nav-group-title\s*\{[^}]*color:\s*var\(--v2-subtle\)/);
  assert.match(shell, /\.nfc-v2-sidebar-footer small\s*\{[^}]*color:\s*var\(--v2-subtle\)/);
});

test('dark Pure White small secondary text passes AA including softened panels', () => {
  const foreground = token(shellDark, '--v2-subtle');
  requireAA('dark shell secondary text', foreground, [
    ['dark canvas', token(shellDark, '--v2-canvas')],
    ['dark paper', token(shellDark, '--v2-paper')],
    ['dark sidebar', token(shellDark, '--v2-sidebar')],
    ['dark sidebar surface', token(shellDark, '--v2-sidebar-surface')],
    ['dark soft neutral surface', token(shellDark, '--v2-indigo-soft')],
  ]);
  requireAA('dark sidebar muted navigation text', token(shellDark, '--v2-sidebar-muted'), [
    ['dark sidebar', token(shellDark, '--v2-sidebar')],
    ['dark sidebar surface', token(shellDark, '--v2-sidebar-surface')],
  ]);
});

test('Radix portal typography keeps the same accessible theme colors as the shell', () => {
  assert.equal(token(portalLight, '--v2-subtle'), token(shellLight, '--v2-subtle'));
  assert.equal(token(portalDark, '--v2-subtle'), token(shellDark, '--v2-subtle'));
  for (const portal of [portalLight, portalDark]) {
    for (const name of ['--v2-canvas', '--v2-paper', '--v2-text', '--v2-muted', '--v2-line', '--v2-indigo-soft']) {
      const base = portal === portalLight ? shellLight : shellDark;
      assert.equal(token(portal, name), token(base, name), name + ' must match shell and portal');
    }
    requireAA('Radix portal small facts and hints', token(portal, '--v2-subtle'), [
      ['portal paper', token(portal, '--v2-paper')],
      ['portal canvas', token(portal, '--v2-canvas')],
      ['portal soft surface', token(portal, '--v2-indigo-soft')],
    ]);
  }
  assert.match(overlays, /\.nfc-v2-task-facts dt\s*\{[^}]*color:\s*var\(--v2-subtle\)/);
});


/**
 * Stage 5E-AL: status badges use normal-size text, which requires WCAG AA
 * 4.5:1 contrast. Cover every exact selector definition, including later
 * !important overrides; testing only the first rule can miss regressions.
 */
function statusRules(css, selector) {
  const escaped = selector.replaceAll('.', '\\.').replaceAll('[', '\\[').replaceAll(']', '\\]');
  const bodies = [...css.matchAll(new RegExp('^' + escaped + '\\s*\\{([^}]*)\\}', 'gm'))]
    .map(match => match[1]);
  assert.ok(bodies.length > 0, 'Missing status rule: ' + selector);
  return bodies;
}

function statusHex(body, property) {
  const found = body.match(new RegExp(
    '(?:^|;)\\s*' + property + '\\s*:\\s*(#[0-9a-fA-F]{6})(?:\\s*!important)?\\s*(?=;|$)',
  ));
  assert.ok(found, 'Missing solid ' + property + ' in status rule');
  return found[1];
}

test('Pure White header status badges meet AA in both themes, including later overrides', () => {
  for (const theme of ['light', 'dark']) {
    for (const state of ['safe', 'warning', 'danger']) {
      const selector = (theme === 'dark' ? "[data-theme='dark'] " : '')
        + '.nfc-v2-header .nfc-header-status-badge.is-' + state;
      for (const body of statusRules(shell, selector)) {
        requireAA(theme + ' ' + state + ' status', statusHex(body, 'color'), [
          ['status background', statusHex(body, 'background')],
        ]);
      }
    }
  }
});

/**
 * Stage 5E-AM: task drawer's tiny capability and event-level chips are
 * normal-size text for WCAG purposes (11px and 10px); the 4.5:1 AA
 * threshold applies even when the status is conveyed with color.
 */
test('Task Inspector supported capability badge meets AA in both themes', () => {
  for (const selector of [
    '.nfc-v2-task-capability.is-supported',
    "[data-theme='dark'] .nfc-v2-task-capability.is-supported",
  ]) {
    for (const body of statusRules(overlays, selector)) {
      requireAA(selector, statusHex(body, 'color'), [
        ['capability background', statusHex(body, 'background')],
      ]);
    }
  }
});

test('Task event log warning and error badges meet AA on their declared backgrounds', () => {
  // These solid badge colors are shared by both themes; fail if a future
  // declaration reduces legibility or removes either status style.
  for (const state of ['warning', 'error']) {
    const selector = '.nfc-v2-log-level.is-' + state;
    for (const body of statusRules(overlays, selector)) {
      requireAA(selector, statusHex(body, 'color'), [
        ['event level background', statusHex(body, 'background')],
      ]);
    }
  }
});
