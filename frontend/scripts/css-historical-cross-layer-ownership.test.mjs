import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = path => readFileSync(resolve(process.cwd(), path), 'utf8');
const detail = read('src/styles/v048-detail.css');
const workspace = read('src/styles/v049-workspace.css');

// Match *only* leaf rules and retain exact ancestor context. Responsive
// overrides must not be mistaken for the unconditional v049 successor.
function cssRules(css) {
  const result = [];
  const stack = [];
  let start = 0, comment = false, quote = null, escape = false;
  for (let i = 0; i < css.length; i += 1) {
    const ch = css[i], next = css[i + 1];
    if (comment) {
      if (ch === '*' && next === '/') { comment = false; i += 1; }
      continue;
    }
    if (quote) {
      if (escape) { escape = false; continue; }
      if (ch === '\\') { escape = true; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '*') { comment = true; i += 1; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === '{') {
      const selector = css.slice(start, i).replace(/\/\*[\s\S]*?\*\//g, '').trim();
      stack.push({ selector, from: i + 1, context: stack
        .filter(entry => entry.selector.startsWith('@')).map(entry => entry.selector).join(' > ') });
      start = i + 1;
    } else if (ch === '}') {
      const entry = stack.pop();
      assert.ok(entry, 'Unbalanced CSS closing brace');
      const text = css.slice(entry.from, i);
      if (!entry.selector.startsWith('@') && !text.includes('{')) {
        const declarations = new Map();
        for (const field of text.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = field.indexOf(':');
          if (colon === -1) continue;
          declarations.set(field.slice(0, colon).trim(), field.slice(colon + 1).trim());
        }
        result.push({ selector: entry.selector, context: entry.context, declarations });
      }
      start = i + 1;
    } else if (ch === ';' && stack.length === 0) {
      start = i + 1;
    }
  }
  assert.equal(stack.length, 0, 'Balanced CSS rule and at-rule ancestry');
  return result;
}

const detailRules = cssRules(detail);
const v049Rules = cssRules(workspace);
const match = (rules, selector, context = '') => rules.filter(rule =>
  rule.selector === selector && rule.context === context);
const finalValue = (selector, prop) => {
  const blocks = match(v049Rules, selector);
  assert.ok(blocks.length > 0, 'Missing v049 winner for ' + selector);
  const winners = blocks.filter(rule => rule.declarations.has(prop));
  assert.ok(winners.length > 0, 'Missing v049 final ' + selector + ' ' + prop);
  return winners.at(-1).declarations.get(prop);
};

test('v048-detail: retire exactly 16 proven cross-file header shadows while pinning live v049 owners', () => {
  const cases = [
    ['.nfc-header-workspace', {
      'min-width': '132px', 'max-width': '210px',
    }],
    ['.nfc-header-workspace-kicker', {
      color: 'var(--nfc-v49-subtle)',
      'font-size': '8px', 'font-weight': '730', 'letter-spacing': '0.14em',
    }],
    ['.nfc-header-workspace-name', {
      'margin-top': '3px', color: 'var(--nfc-v49-text)',
      'font-size': '11px', 'font-weight': '650', 'letter-spacing': '-0.01em',
    }],
    ['.nfc-header-status', {
      gap: '3px', padding: '2px',
      border: '1px solid var(--nfc-v49-line)', 'border-radius': '999px',
      background: 'color-mix(in srgb, var(--nfc-surface-1) 64%, transparent)',
    }],
  ];
  let retired = 0;
  for (const [selector, expected] of cases) {
    const original = match(detailRules, selector);
    assert.ok(original.length <= 1, 'Unexpected v048-detail top-level duplicate ' + selector);
    for (const [prop, value] of Object.entries(expected)) {
      if (original.length === 1) {
        assert.equal(original[0].declarations.has(prop), false,
          'v048-detail earlier shadow returned: ' + selector + ' ' + prop);
      }
      assert.equal(finalValue(selector, prop), value,
        'Later, same-selector v049 authority changed: ' + selector + ' ' + prop);
      retired += 1;
    }
  }
  assert.equal(retired, 16);
  assert.equal(match(detailRules, '.nfc-header-status').length, 0,
    'Completely shadowed desktop status block should remain retired');
});

test('v048-detail: preserve meaningful early properties and responsive-only rules', () => {
  const props = [
    ['.nfc-header-workspace', 'padding-right', '16px'],
    ['.nfc-header-workspace-kicker', 'overflow', 'hidden'],
    ['.nfc-header-workspace-kicker', 'text-overflow', 'ellipsis'],
    ['.nfc-header-workspace-kicker', 'white-space', 'nowrap'],
    ['.nfc-header-workspace-name', 'overflow', 'hidden'],
    ['.nfc-header-workspace-name', 'text-overflow', 'ellipsis'],
    ['.nfc-header-workspace-name', 'white-space', 'nowrap'],
  ];
  for (const [selector, key, value] of props) {
    const matches = match(detailRules, selector);
    assert.equal(matches.length, 1);
    assert.equal(matches[0].declarations.get(key), value);
  }
  const responsiveStatus = detailRules.filter(rule =>
    rule.selector === '.nfc-header-status' && rule.context.startsWith('@media'));
  assert.ok(responsiveStatus.length >= 2, 'Keep responsive header-status scrolling and sizing');
  assert.ok(responsiveStatus.some(rule => rule.declarations.get('scrollbar-width') === 'none'));
  assert.ok(responsiveStatus.some(rule => rule.declarations.get('max-width') === 'calc(100vw - 136px)'));
  for (const marker of ['.nfc-header-status-badge.is-safe',
    '.nfc-header-status-badge.is-warning', '.nfc-header-status-badge.is-danger',
    '.nfc-header-status-badge.is-processing', '.nfc-mobile-pagination']) {
    assert.ok(detail.includes(marker), 'Unrelated native status/mobile CSS still present: ' + marker);
  }
});

test('unconditional later v049 load and readonly Chromium matrices remain CI gated', () => {
  const main = read('src/main.tsx');
  const early = main.indexOf("import './styles/v048-detail.css';");
  const late = main.indexOf("import './styles/v049-workspace.css';");
  const native = main.indexOf("import './styles/console-v2.css';");
  assert.ok(early >= 0 && early < late && late < native,
    'v049 successors must load after v048-detail and before native Console v2');
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  for (const name of ['browser-workspace-cascade.mjs', 'browser-overlay-smoke.mjs',
    'browser-task-ledger-states.mjs', 'browser-indexes-ledger-states.mjs',
    'browser-media-ledger-states.mjs']) {
    assert.ok(ci.includes(name), 'Exact-HEAD browser regression gate missing: ' + name);
  }
  const workspaceBrowser = read('scripts/browser-workspace-cascade.mjs');
  for (const marker of ['360, 390, 430, 768, 1024, 1280, 1440, 1920',
    "request.method() !== 'GET'", 'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []', '32/32 cases, 352 screenshots']) {
    assert.ok(workspaceBrowser.includes(marker),
      'Browser must retain 8-width/theme no-write evidence: ' + marker);
  }
  assert.doesNotMatch(detail, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
});
