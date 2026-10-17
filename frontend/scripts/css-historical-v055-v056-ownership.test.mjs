import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = path => readFileSync(resolve(process.cwd(), path), 'utf8');
const old55 = read('src/styles/v055-workspace-breathing.css');
const late56 = read('src/styles/v056-right-workspace-v2.css');

// Explicitly preserve ancestor @media/@supports conditions instead of
// comparing same-looking selector text from different viewport rules.
function leafRules(css) {
  const rules = [];
  const stack = [];
  let start = 0, comment = false, quote = null, escaped = false;
  for (let i = 0; i < css.length; i += 1) {
    const ch = css[i], next = css[i + 1];
    if (comment) {
      if (ch === '*' && next === '/') { comment = false; i += 1; }
      continue;
    }
    if (quote) {
      if (escaped) { escaped = false; continue; }
      if (ch === '\\') { escaped = true; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '*') { comment = true; i += 1; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === '{') {
      const selector = css.slice(start, i).replace(/\/\*[\s\S]*?\*\//g, '').trim();
      const context = stack.filter(item => item.selector.startsWith('@'))
        .map(item => item.selector).join(' > ');
      stack.push({ selector, context, from: i + 1 });
      start = i + 1;
    } else if (ch === '}') {
      const entry = stack.pop();
      assert.ok(entry, 'Balanced CSS closing brace');
      const body = css.slice(entry.from, i);
      if (!entry.selector.startsWith('@') && !body.includes('{')) {
        const declarations = new Map();
        for (const field of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = field.indexOf(':');
          if (colon >= 0) declarations.set(field.slice(0, colon).trim(),
            field.slice(colon + 1).trim());
        }
        rules.push({ selector: entry.selector, context: entry.context, declarations });
      }
      start = i + 1;
    } else if (ch === ';' && stack.length === 0) start = i + 1;
  }
  assert.equal(stack.length, 0, 'Balanced CSS at-rule ancestry');
  return rules;
}
const early = leafRules(old55);
const late = leafRules(late56);
const matching = (rules, selector, context = '') =>
  rules.filter(rule => rule.selector === selector && rule.context === context);

test('v055 -> v056: 14 exact-selector, identical-context shadows stay retired', () => {
  const cases = [
    ['.nfc-app-main .nfc-page-header', {
      'min-height': '0', margin: '0 0 24px', padding: '0 0 20px',
      'align-items': 'flex-end', gap: '28px', border: '0',
      'border-radius': '0', background: 'transparent', 'box-shadow': 'none',
    }],
    ['.nfc-app-main .nfc-page-header-copy', { 'max-width': 'min(980px, 74vw)' }],
    ['.nfc-app-main .nfc-page-title', { 'line-height': '1.18' }],
    ['.nfc-app-main .nfc-page-description', {
      'max-width': '82ch', 'margin-top': '8px', 'line-height': '1.58',
    }],
  ];
  let count = 0;
  for (const [selector, expected] of cases) {
    assert.equal(matching(early, selector).length, 0,
      'Old unconditional header shadow reintroduced: ' + selector);
    const winners = matching(late, selector);
    assert.equal(winners.length, 1, 'One unconditional v056 owner required: ' + selector);
    for (const [property, value] of Object.entries(expected)) {
      assert.equal(winners[0].declarations.get(property), value,
        'Final v056 owner changed: ' + selector + ' / ' + property);
      assert.ok(!value.includes('!important'), 'Unconditional winners must share importance');
      count += 1;
    }
  }
  assert.equal(count, 14);
  assert.equal(matching(late, '.nfc-app-main .nfc-page-header')[0]
    .declarations.get('border-bottom'), '1px solid var(--nfc-w2-hairline)',
    'Independent late hairline border must survive');
});

test('v055 responsive header authority and independent layouts remain untouched', () => {
  const keep = [
    ['.nfc-app-main .nfc-page-header', '@media (min-width: 1800px)', 'min-height', '146px'],
    ['.nfc-app-main .nfc-page-header', '@media (max-width: 1399px)', 'min-height', '126px'],
    ['.nfc-app-main .nfc-page-header', '@media (max-width: 980px)', 'min-height', '118px'],
    ['.nfc-app-main .nfc-page-header', '@media (max-width: 980px)', 'align-items', 'flex-start'],
    ['.nfc-app-main .nfc-page-header-copy', '@media (min-width: 1800px)', 'max-width', '980px'],
    ['.nfc-app-main .nfc-page-header-copy', '@media (max-width: 980px)', 'width', '100%'],
    ['.nfc-app-main .nfc-page-eyebrow', '', 'margin-bottom', '10px'],
    ['.nfc-app-main .nfc-page-actions', '', 'flex', '0 0 auto'],
    ['.nfc-app-main .nfc-page-header::after', '', 'width', '88px'],
    ['.nfc-app-main .nfc-page-content > .nfc-quarantine-page,\n.nfc-app-main .nfc-page-content > .nfc-tasks-page,\n.nfc-app-main .nfc-page-content > .nfc-media-page,\n.nfc-app-main .nfc-page-content > .nfc-plans-page,\n.nfc-app-main .nfc-page-content > .nfc-scan-detail-page,\n.nfc-app-main .nfc-page-content > .nfc-plan-detail-page', '', 'width', 'min(100%, var(--nfc-v55-dense-max))'],
  ];
  for (const [selector, context, property, expected] of keep) {
    assert.ok(matching(early, selector, context).some(
      rule => rule.declarations.get(property) === expected),
    'Independent/responsive declaration lost: ' + selector + ' ' + context + ' ' + property);
  }
  assert.match(old55, /@media \(max-width: 767px\)/);
});

test('source order and exact-HEAD, read-only Chromium guard remain in CI', () => {
  const entry = read('src/main.tsx');
  const v55 = entry.indexOf("import './styles/v055-workspace-breathing.css';");
  const v56 = entry.indexOf("import './styles/v056-right-workspace-v2.css';");
  const v2 = entry.indexOf("import './styles/console-v2.css';");
  assert.ok(v55 >= 0 && v55 < v56 && v56 < v2);
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  for (const script of ['browser-workspace-cascade.mjs',
    'browser-overlay-smoke.mjs', 'browser-task-ledger-states.mjs',
    'browser-media-ledger-states.mjs']) {
    assert.ok(ci.includes(script), 'Readonly Chromium matrix missing: ' + script);
  }
  const browser = read('scripts/browser-workspace-cascade.mjs');
  for (const invariant of ['360, 390, 430, 768, 1024, 1280, 1440, 1920',
    "request.method() !== 'GET'", 'assert.deepEqual(writes, []',
    'assert.deepEqual(outbound, []']) {
    assert.ok(browser.includes(invariant), 'Browser isolation/viewport lost: ' + invariant);
  }
});

test('v055 -> v056: page frame and nonempty body have four final owned declarations', () => {
  const cases = [
    ['.nfc-app-main .nfc-page-content', {
      padding: '18px clamp(24px, 2.15vw, 42px) var(--nfc-w2-page-bottom)',
    }],
    ['.nfc-app-main .nfc-page-content > *', {
      width: 'min(100%, var(--nfc-w2-content-max))', 'margin-inline': 'auto',
    }],
    ['.nfc-app-main .nfc-data-panel-body:not(:empty)', {
      'min-width': '0',
    }],
  ];
  let checked = 0;
  for (const [selector, props] of cases) {
    assert.equal(matching(early, selector).length, 0,
      'Earlier unconditional owner must stay retired: ' + selector);
    const owner = matching(late, selector);
    assert.equal(owner.length, 1,
      'Later v056 should retain one exact unconditional owner: ' + selector);
    for (const [property, value] of Object.entries(props)) {
      assert.equal(owner[0].declarations.get(property), value,
        'Final v056 declaration differs: ' + selector + ' ' + property);
      assert.ok(!value.includes('!important'), 'No importance escalation permitted');
      checked += 1;
    }
  }
  assert.equal(checked, 4);
  assert.equal(matching(late, '.nfc-app-main .nfc-page-content')[0]
    .declarations.get('scroll-padding-bottom'), 'var(--nfc-w2-page-bottom)',
    'Independent scroll padding must remain');
  const body = matching(late, '.nfc-app-main .nfc-data-panel-body:not(:empty)')[0];
  assert.equal(body.declarations.get('overflow'), 'hidden');
  assert.equal(body.declarations.get('border'), '1px solid var(--nfc-w2-hairline)');
});

test('v055 independent dense width contract and responsive tokens are not retired', () => {
  assert.ok(old55.includes('.nfc-app-main .nfc-page-content > .nfc-quarantine-page,'));
  assert.ok(old55.includes('width: min(100%, var(--nfc-v55-dense-max))'));
  const vars = matching(early, '.nfc-app-main');
  assert.ok(vars.some(rule => rule.declarations.get('--nfc-v55-dense-max') === '1660px'));
  for (const [context, property, value] of [
    ['@media (min-width: 1800px)', '--nfc-v55-dense-max', '1720px'],
    ['@media (max-width: 1399px)', '--nfc-v55-page-gutter', 'clamp(24px, 2.4vw, 34px)'],
    ['@media (max-width: 980px)', '--nfc-v55-page-top', '22px'],
  ]) {
    assert.ok(matching(early, '.nfc-app-main', context).some(
      rule => rule.declarations.get(property) === value),
    'Responsive variable authority lost: ' + context + ' ' + property);
  }
  assert.ok(old55.includes('@media (max-width: 767px)'), 'Phone media context remains');
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  for (const script of ['browser-workspace-cascade.mjs',
    'browser-indexes-ledger-states.mjs', 'browser-media-ledger-states.mjs']) {
    assert.ok(ci.includes(script), 'Real read-only Chromium regression missing ' + script);
  }
});
