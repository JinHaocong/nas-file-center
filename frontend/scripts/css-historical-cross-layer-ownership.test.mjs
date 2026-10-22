import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = path => readFileSync(resolve(process.cwd(), path), 'utf8');
const detail = read('src/styles/v048-detail.css');
const workspace = read('src/styles/v049-workspace.css');
const premium = read('src/styles/v054-premium-system.css');

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
const v054Rules = cssRules(premium);
const v056Rules = cssRules(read('src/styles/v056-right-workspace-v2.css'));
const match = (rules, selector, context = '') => rules.filter(rule =>
  rule.selector === selector && rule.context === context);
// A later tranche migrated only these six same-selector properties to v054.
// Keep all independent v049 values pinned, without relabeling old v048 closure
// evidence or implicitly treating different specificity/context as winners.
const migrated = new Map([
  ['.nfc-header-workspace-kicker', new Set(['color', 'font-size', 'letter-spacing'])],
  ['.nfc-header-workspace-name', new Set(['font-size', 'font-weight', 'letter-spacing'])],
  ['.nfc-header-status', new Set(['gap', 'padding', 'border', 'background'])],
]);
const finalValue = (selector, prop) => {
  const moved = migrated.get(selector)?.has(prop) ?? false;
  const earlier = match(v049Rules, selector);
  const blocks = moved ? match(selector === '.nfc-header-status' ? v056Rules : v054Rules,
    selector) : earlier;
  assert.ok(blocks.length > 0, 'Missing later CSS owner for ' + selector);
  if (moved) assert.ok(earlier.every(rule => !rule.declarations.has(prop)),
    'Old v049 migrated property was reintroduced: ' + selector + ' ' + prop);
  const winners = blocks.filter(rule => rule.declarations.has(prop));
  assert.ok(winners.length > 0, 'Missing final CSS owner ' + selector + ' ' + prop);
  return winners.at(-1).declarations.get(prop);
};

test('v048-detail: retain 16 shadow retirements and track subsequent v049/v054 owners', () => {
  const cases = [
    ['.nfc-header-workspace', {
      'min-width': '132px', 'max-width': '210px',
    }],
    ['.nfc-header-workspace-kicker', {
      color: 'var(--nfc-text-subtle)',
      'font-size': '8.5px', 'font-weight': '730', 'letter-spacing': '0.14em',
    }],
    ['.nfc-header-workspace-name', {
      'margin-top': '3px', color: 'var(--nfc-v49-text)',
      'font-size': '12px', 'font-weight': '680', 'letter-spacing': '-0.01em',
    }],
    ['.nfc-header-status', {
      gap: '5px', padding: '0',
      border: '0', 'border-radius': '999px',
      background: 'transparent',
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
        'Later same-selector v049/v054 authority changed: ' + selector + ' ' + prop);
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
  assert.ok(responsiveStatus.every(rule => !rule.declarations.has('scrollbar-width')),
    'Retired phone scrollbar duplicate should not return');
  const finalPhoneStatus = cssRules(read('src/styles/v056-right-workspace-v2.css'))
    .filter(rule => rule.selector === '.nfc-header-status' &&
      rule.context === '@media (max-width: 767px)');
  assert.ok(finalPhoneStatus.some(rule => rule.declarations.get('scrollbar-width') === 'none'),
    'Final v056 phone status must preserve hidden scrollbar');
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
