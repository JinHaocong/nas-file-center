import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Inventory leaf rules together with their exact @media/@supports ancestry.
// Do not flatten media blocks or make assumptions from one global regex match.
function leafRules(css) {
  const output = [];
  const stack = [];
  let segmentStart = 0;
  let quote = null;
  let comment = false;
  let escaped = false;
  for (let index = 0; index < css.length; index += 1) {
    const current = css[index];
    const next = css[index + 1];
    if (comment) {
      if (current === '*' && next === '/') { comment = false; index += 1; }
      continue;
    }
    if (quote) {
      if (escaped) { escaped = false; continue; }
      if (current === '\\') { escaped = true; continue; }
      if (current === quote) quote = null;
      continue;
    }
    if (current === '/' && next === '*') { comment = true; index += 1; continue; }
    if (current === '"' || current === "'") { quote = current; continue; }
    if (current === '{') {
      const selector = css.slice(segmentStart, index).replace(/\/\*[\s\S]*?\*\//g, '').trim();
      const context = stack.filter(entry => entry.selector.startsWith('@')).map(entry => entry.selector).join(' > ');
      stack.push({ selector, context, bodyStart: index + 1 });
      segmentStart = index + 1;
    } else if (current === '}') {
      const entry = stack.pop();
      assert.ok(entry, 'CSS close brace must have opening selector');
      const body = css.slice(entry.bodyStart, index);
      if (!entry.selector.startsWith('@') && !body.includes('{')) {
        const declarations = new Map();
        for (const raw of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = raw.indexOf(':');
          if (colon < 0) continue;
          declarations.set(raw.slice(0, colon).trim(), raw.slice(colon + 1).trim());
        }
        output.push({ selector: entry.selector, context: entry.context, declarations });
      }
      segmentStart = index + 1;
    } else if (current === ';' && stack.length === 0) segmentStart = index + 1;
  }
  assert.equal(stack.length, 0, 'CSS @media and rules remain balanced');
  return output;
}

const read = filename => readFileSync(resolve(process.cwd(), filename), 'utf8');
const old049 = read('src/styles/v049-workspace.css');
const old056 = read('src/styles/v056-right-workspace-v2.css');
const v049 = leafRules(old049);
const v056 = leafRules(old056);
const canonicalSelector = selector => selector.replace(/\s+/g, ' ').replace(/\s*,\s*/g, ',').trim();
const matching = (rules, selector, context = '') => rules.filter(rule =>
  canonicalSelector(rule.selector) === canonicalSelector(selector) && rule.context === context);

test('v049 desktop: 5 earlier shadows retired without changing late winners', () => {
  const header = matching(v049, '.nfc-header.nfc-header');
  assert.equal(header.length, 2);
  assert.equal(header[0].declarations.has('background'), false);
  assert.equal(header[0].declarations.get('position'), 'sticky');
  assert.equal(header[0].declarations.get('z-index'), '30');
  assert.equal(header[1].declarations.get('background'),
    'color-mix(in srgb, var(--nfc-nav-surface) 86%, transparent) !important');

  const toolbar = matching(v049, '.nfc-filter-bar,\n.nfc-bulk-action-bar');
  assert.equal(toolbar.length, 2);
  for (const [property, winner] of Object.entries({
    'min-height': '56px',
    padding: '9px 12px',
    'border-color': 'var(--nfc-border-soft) !important',
    background: 'var(--nfc-ui-panel-bg-soft) !important',
  })) {
    assert.equal(toolbar[0].declarations.has(property), false, 'early toolbar ' + property);
    assert.equal(toolbar[1].declarations.get(property), winner, 'final toolbar ' + property);
  }
  assert.equal(toolbar[0].declarations.get('box-shadow'), 'none !important');
});

test('v049 phone: 9 earlier same-@media shadows retired; later authority unchanged', () => {
  const context = '@media (max-width: 767px)';
  const cases = [
    ['.nfc-page-header', [['margin-bottom', '14px'], ['padding', '16px']]],
    ['.nfc-page-title', [['font-size', '22px']]],
    ['.nfc-page-description', [['font-size', '11px']]],
    ['.nfc-data-panel-header', [['min-height', '56px'], ['padding', '12px 14px']]],
    ['.nfc-data-panel-description', [['display', 'block']]],
    ['.nfc-metric-card', [['padding', '12px 13px']]],
    ['.nfc-system-controls-page .nfc-settings-grid > .nfc-data-panel > .nfc-data-panel-body',
      [['padding', '14px']]],
  ];
  let retired = 0;
  for (const [selector, checks] of cases) {
    const rules = matching(v049, selector, context);
    assert.ok(rules.length === 1 || rules.length === 2,
      selector + ': unexpected exact-context selector duplication');
    for (const [property, finalValue] of checks) {
      const winner = rules.at(-1);
      assert.equal(winner.declarations.get(property), finalValue,
        selector + ': late ' + property + ' has changed');
      if (rules.length === 2) assert.equal(rules[0].declarations.has(property), false,
        selector + ': earlier ' + property + ' must remain retired');
      retired += 1;
    }
  }
  assert.equal(retired, 9);
  const firstHeader = matching(v049, '.nfc-page-header', context)[0];
  assert.equal(firstHeader.declarations.get('min-height'), 'auto');
  assert.equal(matching(v049, '.nfc-filter-bar,\n.nfc-bulk-action-bar', context)[0]
    .declarations.get('padding'), '9px 10px',
    'Distinct responsive toolbar authority must survive');
  assert.equal(matching(v049, '.nfc-metric-card:nth-child(2n)', context)[0]
    .declarations.get('border-right'), '0');
  assert.equal([...old049.matchAll(/@media\s*\([^)]*\)/g)].length, 8,
    'Do not remove or reorder responsive contexts');
});

test('v056 dashboard rail keeps only the late 14px baseline and responsive owners', () => {
  const base = matching(v056, '.nfc-app-main .nfc-dashboard-page .nfc-dashboard-rail');
  assert.equal(base.length, 2, 'Keep late rail spacing and separate position-only authority');
  assert.equal(base[0].declarations.get('gap'), '14px');
  assert.equal(base[1].declarations.get('position'), 'static',
    'The separate late positioning rule must survive');
  assert.equal(base[1].declarations.has('gap'), false,
    'Position-only rule must not reintroduce stale gap');
  assert.ok(base.every(rule => rule.declarations.get('gap') !== '16px'),
    'Old desktop rail gap was already overridden and must stay retired');
  const responsive = matching(v056, '.nfc-app-main .nfc-dashboard-page .nfc-dashboard-rail',
    '@media (max-width: 1199px)');
  assert.ok(responsive.some(rule => rule.declarations.get('gap') === '12px'),
    'Tablet rail gap remains separately owned');
  assert.match(old056, /@media \(max-width: 767px\)[\s\S]*?\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-rail\s*\{[^}]*grid-template-columns:\s*1fr;/);
});

test('import and independent CSS authority unchanged; browser evidence remains gated', () => {
  const entry = read('src/main.tsx');
  const cssOrder = ["./styles/v048-detail.css", "./styles/v049-workspace.css",
    "./styles/v050-layout.css", "./styles/v055-workspace-breathing.css",
    "./styles/v056-right-workspace-v2.css", "./styles/console-v2.css"];
  for (let i = 1; i < cssOrder.length; i += 1) {
    assert.ok(entry.indexOf(cssOrder[i - 1]) < entry.indexOf(cssOrder[i]),
      'Original CSS import cascade order changed at ' + cssOrder[i]);
  }
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
  const workflow = read('../.github/workflows/ui-v044-validation.yml');
  for (const script of [
    'browser-workspace-cascade.mjs',
    'browser-task-ledger-states.mjs',
    'browser-indexes-ledger-states.mjs',
    'browser-media-ledger-states.mjs',
    'browser-overlay-smoke.mjs',
  ]) assert.ok(workflow.includes(script), 'Read-only viewport/theme evidence missing ' + script);
  const visual = read('scripts/browser-workspace-cascade.mjs');
  for (const token of ["request.method() !== 'GET'", "assert.deepEqual(writes, []",
    "assert.deepEqual(outbound, []", '32/32 cases, 352 screenshots']) {
    assert.ok(visual.includes(token), 'No-write browser gate missing ' + token);
  }
});

test('v049 -> v056: 16 obsolete unconditional filter/description declarations stay retired', () => {
  // The earlier files still own responsive and independent surfaces, but
  // v056 owns these exact unconditional selectors at equal specificity.
  const cases = [[".nfc-filter-control",[["gap","6px","7px"],["color","var(--nfc-v49-subtle)","var(--nfc-w2-text-muted)"],["font-size","9.5px","11.5px"],["font-weight","620","600"]]],[".nfc-description-item",[["min-height","72px","78px"],["padding","12px 14px","14px 16px"],["border-color","var(--nfc-v49-line)","var(--nfc-w2-hairline)"]]],[".nfc-description-item dt",[["margin-bottom","6px","7px"],["color","var(--nfc-v49-subtle)","var(--nfc-w2-text-subtle)"],["font-size","8.5px","11px"],["font-weight","680","620"]]],[".nfc-description-item dd",[["color","var(--nfc-v49-muted)","var(--nfc-w2-text-muted)"],["font-size","11px","12.5px"]]],[".nfc-description-item dd.nfc-description-emphasis",[["color","var(--nfc-v49-text)","var(--nfc-w2-text)"],["font-size","13.5px","14px"],["font-weight","650","650"]]]];
  let total = 0;
  for (const [selector, declarations] of cases) {
    assert.equal(matching(v049, selector).length, 0,
      'Obsolete v049 unconditional block returned: ' + selector);
    const owner = matching(v056, selector);
    assert.equal(owner.length, 1, 'One final v056 owner expected for ' + selector);
    for (const [property, previous, current] of declarations) {
      assert.equal(owner[0].declarations.get(property), current,
        'Final v056 property changed: ' + selector + ' / ' + property);
      assert.ok(!previous.includes('!important') && !current.includes('!important'),
        'Exact CSS importance contract must not be elevated');
      total += 1;
    }
  }
  assert.equal(total, 16);
});

test('v049 responsive, themed and important description-frame owners remain intact', () => {
  const frame = matching(v049, '.nfc-responsive-descriptions');
  assert.equal(frame.length, 1, 'Description container still has one native owner');
  for (const [name,expected] of Object.entries({
    overflow: 'clip',
    border: '1px solid var(--nfc-v49-line) !important',
    'border-radius': 'var(--nfc-v49-radius-lg) !important',
    background: 'var(--nfc-v49-surface) !important',
  })) {
    assert.equal(frame[0].declarations.get(name), expected, 'Description frame '+ name);
  }
  assert.match(old049, /@media \(max-width: 767px\)/);
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
  assert.ok(matching(v049, '.nfc-search-input')[0]
    .declarations.get('min-width') === '210px',
    'Filter input native minimum remains separate');
});
