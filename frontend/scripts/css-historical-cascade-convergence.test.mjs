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
const old048 = read('src/styles/v048-detail.css');
const old049 = read('src/styles/v049-workspace.css');
const old054 = read('src/styles/v054-premium-system.css');
const old055 = read('src/styles/v055-workspace-breathing.css');
const old056 = read('src/styles/v056-right-workspace-v2.css');
const v048 = leafRules(old048);
const v049 = leafRules(old049);
const v054 = leafRules(old054);
const v055 = leafRules(old055);
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

test('v049 → v056: 16 old dashboard quick-action and summary row shadows stay retired', () => {
  const cases = [
  [
    ".nfc-dashboard-page .nfc-quick-action",
    [
      [
        "min-height",
        "66px"
      ],
      [
        "padding",
        "11px 14px"
      ],
      [
        "grid-template-columns",
        "32px minmax(0, 1fr) 14px"
      ],
      [
        "border-bottom-color",
        "var(--nfc-w2-hairline)"
      ]
    ]
  ],
  [
    ".nfc-dashboard-page .nfc-quick-action-icon",
    [
      [
        "width",
        "32px"
      ],
      [
        "height",
        "32px"
      ],
      [
        "border",
        "0"
      ],
      [
        "border-radius",
        "9px"
      ],
      [
        "color",
        "var(--nfc-w2-text-muted)"
      ],
      [
        "background",
        "var(--nfc-w2-surface-strong)"
      ]
    ]
  ],
  [
    ".nfc-dashboard-page .nfc-quick-action-copy strong",
    [
      [
        "font-size",
        "12.75px"
      ]
    ]
  ],
  [
    ".nfc-dashboard-page .nfc-quick-action-copy span",
    [
      [
        "font-size",
        "11.5px"
      ]
    ]
  ],
  [
    ".nfc-dashboard-page .nfc-summary-row",
    [
      [
        "min-height",
        "48px"
      ],
      [
        "padding-inline",
        "14px"
      ],
      [
        "border-bottom-color",
        "var(--nfc-w2-hairline)"
      ],
      [
        "font-size",
        "12.5px"
      ]
    ]
  ]
];
  let retired = 0;
  for (const [selector, properties] of cases) {
    assert.equal(matching(v049, selector).length, 0,
      'Old unconditional v049 rule must stay retired: ' + selector);
    const owners = matching(v056, selector);
    assert.equal(owners.length, 1, 'One later v056 unconditional owner: ' + selector);
    for (const [property, value] of properties) {
      assert.equal(owners[0].declarations.get(property), value,
        'Final v056 dashboard owner changed: ' + selector + ' / ' + property);
      assert.ok(!value.includes('!important'), 'No importance escalation permitted');
      retired += 1;
    }
  }
  assert.equal(retired, 16);
});

test('v049 dashboard layout shadows retire while important native rail stays independent', () => {
  const selector = '.nfc-dashboard-page .nfc-dashboard-layout';
  const obsolete = matching(v049, selector);
  assert.equal(obsolete.length, 0,
    'Old unconditional dashboard geometry must not be reintroduced');
  const canonical = matching(v056, selector);
  assert.equal(canonical.length, 1);
  assert.equal(canonical[0].declarations.get('margin-top'), '24px');
  assert.equal(canonical[0].declarations.get('grid-template-columns'),
    'minmax(0, 1fr) minmax(300px, 340px)');
  assert.equal(canonical[0].declarations.get('gap'), '30px');
  assert.equal(matching(v049, selector, '@media (min-width: 1600px)')[0]
    .declarations.get('gap'), '24px',
    'Retain the separate wide-screen dashboard rule');
  assert.equal(matching(v049, selector, '@media (max-width: 1199px)')[0]
    .declarations.get('grid-template-columns'), '1fr',
    'Retain the original tablet grid');
  const rail = matching(v049, '.nfc-dashboard-page .nfc-dashboard-rail > .nfc-data-panel');
  assert.equal(rail.length, 1);
  for (const [prop, expected] of Object.entries({
    border: '1px solid var(--nfc-v49-line) !important',
    'border-radius': 'var(--nfc-v49-radius-lg) !important',
    background: 'color-mix(in srgb, var(--nfc-v49-surface) 76%, transparent) !important',
    'box-shadow': 'none !important',
  })) assert.equal(rail[0].declarations.get(prop), expected,
    'Important native rail frame must remain: ' + prop);
  assert.match(old049, /@media \(max-width: 767px\)/);
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v049 metric typography and snapshot surface: 17 shadows retired, v056 remains owner', () => {
  // Only compare unconditional, exactly matching single selectors and the same
  // CSS properties; no shorthand, grouped selector or media inference.
  const cases = [
    ['.nfc-metric-label', {
      color: 'var(--nfc-w2-text-muted)',
      'font-size': '11.5px',
      'font-weight': '610',
      'letter-spacing': '0',
    }],
    ['.nfc-metric-value', {
      color: 'var(--nfc-w2-text)',
      'font-size': 'clamp(25px, 2vw, 31px)',
      'font-weight': '660',
      'letter-spacing': '-0.045em',
    }],
    ['.nfc-metric-meta', {
      'margin-top': '9px',
      color: 'var(--nfc-w2-text-subtle)',
      'font-size': '11.5px',
    }],
    ['.nfc-dashboard-page .nfc-snapshot-note', {
      'margin-bottom': '20px',
      padding: '11px 14px',
      border: '0',
      'border-radius': 'var(--nfc-w2-radius-sm)',
      color: 'var(--nfc-w2-text-muted)',
      background: 'var(--nfc-w2-surface-soft)',
    }],
  ];
  let retired = 0;
  for (const [selector, finalProperties] of cases) {
    const historical = matching(v049, selector);
    const winner = matching(v056, selector);
    assert.equal(winner.length, 1, 'One final unconditional v056 owner: ' + selector);
    for (const [property, value] of Object.entries(finalProperties)) {
      assert.ok(historical.every(rule => !rule.declarations.has(property)),
        'Retired v049 property reintroduced: ' + selector + ' / ' + property);
      assert.equal(winner[0].declarations.get(property), value,
        'Final v056 property changed: ' + selector + ' / ' + property);
      assert.ok(!value.includes('!important'), 'No importance escalation: ' + selector);
      retired += 1;
    }
  }
  assert.equal(retired, 17);
  assert.equal(matching(v049, '.nfc-metric-label').length, 0);
  assert.equal(matching(v049, '.nfc-metric-meta').length, 0);
  // Preserve independent earlier declarations, not targeted for retirement.
  assert.equal(matching(v049, '.nfc-metric-value').length, 1);
  assert.equal(matching(v049, '.nfc-metric-value')[0]
    .declarations.get('margin-top'), '12px');
  assert.equal(matching(v049, '.nfc-dashboard-page .nfc-snapshot-note').length, 1);
  assert.equal(matching(v049, '.nfc-dashboard-page .nfc-snapshot-note')[0]
    .declarations.get('box-shadow'), 'none');
  assert.ok(v056.some(rule => rule.context.startsWith('@media') &&
    rule.selector === '.nfc-metric-label' && rule.declarations.get('font-size') === '11px'),
  'Responsive 11px metric label must remain');
  assert.ok(v056.some(rule => rule.context.startsWith('@media') &&
    rule.selector === '.nfc-metric-value' && rule.declarations.get('font-size') === '23px'),
  'Responsive 23px metric value must remain');
  assert.equal([...old049.matchAll(/@media\s*\([^)]*\)/g)].length, 8,
    'Retain all eight historical media contexts');
});


test('v049 workspace frame, action and metric-grid: 16 exact v056 shadows retired', () => {
  // All retired declarations are unconditional single-selector, same-property
  // and equal-importance losers to later-imported v056 declarations.
  const owners = [
    ['.nfc-page-content', {
      position: 'relative',
      width: '100%',
      'min-width': '0',
      padding: '18px clamp(24px, 2.15vw, 42px) var(--nfc-w2-page-bottom)',
    }],
    ['.nfc-page-content > *', {
      width: 'min(100%, var(--nfc-w2-content-max))',
      'margin-inline': 'auto',
    }],
    ['.nfc-header-action-label', {
      color: 'var(--nfc-w2-text-muted)',
      'font-size': '12px',
    }],
    ['.nfc-page-actions', {
      'align-self': 'flex-end',
      gap: '8px',
    }],
    ['.nfc-metric-grid', {
      overflow: 'visible',
      gap: '12px',
      border: '0',
      'border-radius': '0',
      background: 'transparent',
      'box-shadow': 'none',
    }],
  ];
  let retired = 0;
  for (const [selector, declarations] of owners) {
    const earlier = matching(v049, selector);
    const winners = matching(v056, selector);
    assert.equal(winners.length, 1, selector + ': one unconditional v056 owner');
    for (const [property, finalValue] of Object.entries(declarations)) {
      assert.ok(earlier.every(rule => !rule.declarations.has(property)),
        selector + ': retired v049 shadow returned: ' + property);
      assert.equal(winners[0].declarations.get(property), finalValue,
        selector + ': v056 winner changed: ' + property);
      assert.ok(!finalValue.includes('!important'),
        selector + ': no importance escalation');
      retired += 1;
    }
  }
  assert.equal(retired, 16);
  assert.equal(matching(v049, '.nfc-page-content')[0].declarations.get('z-index'), '1',
    'Keep independent page stacking contract');
  assert.equal(matching(v049, '.nfc-page-actions').length, 1);
  assert.equal(matching(v049, '.nfc-page-actions')[0].declarations.get('padding-bottom'), '0',
    'Keep later v049 action-row property');
  assert.equal(matching(v049, '.nfc-page-content > *').length, 0);
  assert.equal(matching(v049, '.nfc-header-action-label').length, 0);
  assert.equal(matching(v049, '.nfc-metric-grid').length, 0,
    'Empty old and superseded baseline metric-grid rules stay retired');
  assert.equal(matching(v049, '.nfc-metric-grid',
    '@media (max-width: 420px)')[0].declarations.get('grid-template-columns'),
  '1fr 1fr', 'Distinct 420px metric-column owner must survive');
  assert.equal(matching(v049, '.nfc-metric-grid',
    '@media (max-width: 767px)')[0].declarations.get('grid-template-columns'),
  'repeat(2, minmax(0, 1fr))', 'Distinct phone metric columns survive');
  assert.equal([...old049.matchAll(/@media\s*\([^)]*\)/g)].length, 8);
  const entry = read('src/main.tsx');
  const old = entry.indexOf("import './styles/v049-workspace.css';");
  const late = entry.indexOf("import './styles/v056-right-workspace-v2.css';");
  assert.ok(old >= 0 && old < late, 'v056 continues owning final frame and metric geometry');
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v049-v054: 14 shadowed header identity, code and overlay properties stay v054-owned', () => {
  // Only unconditional single selectors, matching specificity and normal
  // importance. No media flattening or shorthand/longhand equivalence.
  const cases = [
    ['.nfc-header-workspace-kicker', {
      color: 'var(--nfc-text-subtle)',
      'font-size': '8.5px',
      'letter-spacing': '0.14em',
    }, {'font-weight': '730'}],
    ['.nfc-header-workspace-name', {
      'font-size': '12px',
      'font-weight': '680',
      'letter-spacing': '-0.01em',
    }, {'margin-top': '3px', color: 'var(--nfc-v49-text)'}],
    ['.nfc-code-block', {
      padding: '12px 13px',
      'border-radius': '10px',
      color: 'var(--nfc-text-muted)',
      background: 'color-mix(in srgb, var(--nfc-surface-2) 62%, var(--nfc-surface-1))',
      'font-size': '10px',
    }, {'border-color': 'var(--nfc-v49-line)'}],
    ['.nfc-overlay-section-header', {
      'min-height': '52px',
      padding: '11px 13px',
      background: 'color-mix(in srgb, var(--nfc-surface-2) 48%, transparent)',
    }, {'border-bottom-color': 'var(--nfc-border-soft)'}],
  ];
  let retired = 0;
  for (const [selector, owners, independent] of cases) {
    const early = matching(v049, selector);
    const late = matching(v054, selector);
    assert.equal(late.length, 1, selector + ' needs one unconditional v054 winner');
    assert.equal(early.length, selector === '.nfc-overlay-section-header' ? 2 : 1,
      'Retain existing historical rule identities: ' + selector);
    const retained = early.at(-1);
    for (const [name, expected] of Object.entries(owners)) {
      assert.ok(early.every(rule => !rule.declarations.has(name)),
        selector + ' obsolete v049 declaration returned: ' + name);
      assert.equal(late[0].declarations.get(name), expected,
        selector + ' v054 owner drifted: ' + name);
      assert.ok(!expected.includes('!important'), 'No cascade importance escalation');
      retired++;
    }
    for (const [name, value] of Object.entries(independent)) {
      assert.equal(retained.declarations.get(name), value,
        'Preserve independent v049 contract: ' + selector + ' / ' + name);
    }
  }
  assert.equal(retired, 14);
  assert.equal(matching(v054, '.nfc-code-block', '@media (max-width: 420px)')[0]
    .declarations.get('font-size'), '9.5px',
    'v054 420px code typography must survive');
  assert.equal(matching(v054, '.nfc-code-block', '@media (max-width: 420px)')[0]
    .declarations.get('padding'), '10px',
    'v054 420px code padding must survive');
  assert.equal(matching(v054, '.nfc-overlay-section-header', '@media (max-width: 767px)')[0]
    .declarations.get('padding'), '10px 11px',
    'v054 mobile overlay header padding must survive');
  assert.equal([...old049.matchAll(/@media\s*\([^)]*\)/g)].length, 8);
  const entry = read('src/main.tsx');
  const oldPosition = entry.indexOf("import './styles/v049-workspace.css';");
  const laterPosition = entry.indexOf("import './styles/v054-premium-system.css';");
  assert.ok(oldPosition >= 0 && oldPosition < laterPosition,
    'v054 must remain later in CSS import cascade');
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v049 workflow step and row action: 9 same-selector v056 declarations are sole owners', () => {
  const cases = [
    ['.nfc-row-actions', {
      gap: '2px',
      opacity: '0.56',
    }],
    ['.nfc-workflow-builder-page .nfc-workflow-step-card.is-expanded', {
      background: 'var(--nfc-w2-surface) !important',
      'box-shadow': 'inset 3px 0 0 color-mix(in srgb, var(--nfc-w2-accent) 66%, transparent) !important',
    }],
    ['.nfc-workflow-builder-page .nfc-workflow-step-heading', {
      'min-height': '62px',
      padding: '11px 15px',
    }],
    ['.nfc-workflow-builder-page .nfc-workflow-step-editor', {
      padding: '18px 16px 20px',
      'border-top': '1px solid var(--nfc-w2-hairline)',
      background: 'var(--nfc-w2-surface-soft)',
    }],
  ];
  let retired = 0;
  for (const [selector, declared] of cases) {
    assert.equal(matching(v049, selector).length, 0, selector + ': obsolete unconditional rule returned');
    const winners = matching(v056, selector);
    assert.equal(winners.length, 1, selector + ': expected one unconditional v056 authority');
    for (const [property, value] of Object.entries(declared)) {
      assert.equal(winners[0].declarations.get(property), value,
        selector + ': final v056 property changed: ' + property);
      retired++;
    }
  }
  assert.equal(retired, 9);
  // Do not remove the separate keyboard/native row focus and phone overrides.
  assert.equal(matching(v049, '.nfc-row-actions:focus-within').length, 1);
  assert.equal(matching(v049, '.nfc-row-actions:focus-within')[0]
    .declarations.get('opacity'), '1');
  assert.equal(matching(v049, '.nfc-row-actions', '@media (max-width: 767px)')[0]
    .declarations.get('opacity'), '1');
  const mobile = matching(v049,
    '.nfc-workflow-builder-page .nfc-workflow-step-heading,\n.nfc-workflow-builder-page .nfc-workflow-step-editor',
    '@media (max-width: 767px)');
  assert.equal(mobile.length, 1, 'Retain the grouped phone workflow step gutter override');
  assert.equal(mobile[0].declarations.get('padding-inline'), '10px');
  // Unchanged legacy ancestry and later-imported final authority.
  assert.equal([...old049.matchAll(/@media\s*\([^)]*\)/g)].length, 8);
  const imports = read('src/main.tsx');
  assert.ok(imports.indexOf("import './styles/v049-workspace.css';") <
    imports.indexOf("import './styles/v056-right-workspace-v2.css';"));
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v054-v056: 13 exact typography shadows retire with historical colors retained', () => {
  // Exact single-selector specificity, unconditional ancestry, normal
  // importance; responsive and independent earlier colors remain.
  const cases = [
    ['.nfc-app-main .nfc-page-title', {
      'font-size': 'clamp(27px, 1.45vw, 31px)',
      'font-weight': '620',
      'line-height': '1.18',
      'letter-spacing': '-0.014em',
      'text-wrap': 'balance',
    }, 'var(--nfc-text)'],
    ['.nfc-app-main .nfc-page-description', {
      'max-width': '82ch',
      'margin-top': '8px',
      'font-size': '13px',
      'line-height': '1.58',
    }, 'var(--nfc-text-muted)'],
    ['.nfc-app-main .nfc-data-panel-title', {
      'font-size': '14px',
      'font-weight': '620',
      'line-height': '1.42',
      'letter-spacing': '-0.004em',
    }, 'var(--nfc-text)'],
  ];
  let retired = 0;
  for (const [selector, declarations, retainedColor] of cases) {
    const old = matching(v054, selector);
    const owners = matching(v056, selector);
    assert.equal(old.length, 1, selector + ': one historical color-only rule');
    assert.equal(owners.length, 1, selector + ': one final v056 owner');
    assert.equal(old[0].declarations.size, 1, selector + ': only independent color survives');
    assert.equal(old[0].declarations.get('color'), retainedColor, selector + ': v054 color preserved');
    for (const [property, expected] of Object.entries(declarations)) {
      assert.equal(old[0].declarations.has(property), false, selector + ': obsolete ' + property);
      assert.equal(owners[0].declarations.get(property), expected, selector + ': v056 final ' + property);
      assert.ok(!expected.includes('!important'), 'normal cascade importance unchanged');
      retired++;
    }
  }
  assert.equal(retired, 13);
  const mobile = '@media (max-width: 767px)';
  const phone = '@media (max-width: 420px)';
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-title', mobile)[0]
    .declarations.get('font-size'), '23px');
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-description', mobile)[0]
    .declarations.get('line-height'), '1.6');
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-title', phone)[0]
    .declarations.get('font-size'), '22px');
  assert.equal(matching(v056, '.nfc-app-main .nfc-page-title', mobile)[0]
    .declarations.get('font-size'), '24px');
  assert.equal(matching(v056, '.nfc-app-main .nfc-page-title', phone)[0]
    .declarations.get('font-size'), '22px');
  assert.equal(matching(v056, '.nfc-app-main .nfc-page-description', mobile)[0]
    .declarations.get('font-size'), '12.75px');
  assert.equal(matching(v056, '.nfc-app-main .nfc-data-panel-title', mobile)[0]
    .declarations.get('font-size'), '13.5px');
  const imports = read('src/main.tsx');
  const early = imports.indexOf("import './styles/v054-premium-system.css';");
  const late = imports.indexOf("import './styles/v056-right-workspace-v2.css';");
  assert.ok(early >= 0 && early < late, 'Preserve canonical import order');
  assert.match(old054, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old054, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v054-v056: 10 shadowed header layout and panel-description declarations retire', () => {
  // Ten unconditional normal-priority declarations had later owners under
  // exactly the same single selector. Never derive safety from related
  // shorthands, selector groups or responsive/important declarations.
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-header').length, 0,
    'Obsolete six-property v054 page-header rule must not return');
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-header-copy').length, 0,
    'Obsolete one-property v054 header-copy rule must not return');

  const headerOwner = matching(v056, '.nfc-app-main .nfc-page-header');
  const copyOwner = matching(v056, '.nfc-app-main .nfc-page-header-copy');
  assert.equal(headerOwner.length, 1, 'Exactly one unconditional v056 header owner');
  assert.equal(copyOwner.length, 1, 'Exactly one unconditional v056 copy owner');
  const headerProps = {
    'min-height': '0',
    margin: '0 0 24px',
    padding: '0 0 20px',
    'align-items': 'flex-end',
    gap: '28px',
    'border-bottom': '1px solid var(--nfc-w2-hairline)',
  };
  for (const [property, value] of Object.entries(headerProps)) {
    assert.equal(headerOwner[0].declarations.get(property), value, 'v056 header: ' + property);
    assert.ok(!value.includes('!important'), 'Do not alter priority: ' + property);
  }
  assert.equal(copyOwner[0].declarations.get('max-width'), 'min(980px, 74vw)');
  assert.equal(headerOwner[0].declarations.get('border'), '0',
    'Preserve v056 border reset alongside final border-bottom');
  assert.equal(copyOwner[0].declarations.get('min-width'), '0');

  const oldDescription = matching(v054, '.nfc-app-main .nfc-data-panel-description');
  const newDescription = matching(v056, '.nfc-app-main .nfc-data-panel-description');
  assert.equal(oldDescription.length, 1);
  assert.equal(newDescription.length, 1);
  assert.deepEqual([...oldDescription[0].declarations], [
    ['max-width', '86ch'],
    ['color', 'var(--nfc-text-subtle)'],
  ], 'Independent v054 width and theme color remain untouched');
  for (const [property, value] of Object.entries({
    'margin-top': '5px', 'font-size': '11.5px', 'line-height': '1.52',
  })) {
    assert.equal(oldDescription[0].declarations.has(property), false);
    assert.equal(newDescription[0].declarations.get(property), value);
    assert.ok(!value.includes('!important'));
  }
  assert.equal(Object.keys(headerProps).length + 1 + 3, 10);

  // The ornament retains distinct historical ownership even though v056
  // hides it; v055 decorations and responsive overrides are not flattened.
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-header::after')[0]
    .declarations.get('position'), 'absolute');
  const v055 = leafRules(read('src/styles/v055-workspace-breathing.css'));
  assert.equal(matching(v055, '.nfc-app-main .nfc-page-header::after')[0]
    .declarations.get('width'), '88px');
  assert.equal(matching(v056, '.nfc-app-main .nfc-page-header::after')[0]
    .declarations.get('display'), 'none');
  assert.equal(matching(v056, '.nfc-app-main .nfc-page-header',
    '@media (max-width: 1199px)')[0].declarations.get('flex-wrap'), 'wrap');
  assert.equal(matching(v056, '.nfc-app-main .nfc-page-header',
    '@media (max-width: 767px)')[0].declarations.get('margin-bottom'), '22px');
  assert.ok(matching(v056, '.nfc-app-main .nfc-page-header',
    '@media (max-width: 767px)').some(rule =>
    rule.declarations.get('justify-content') === 'flex-start'));
  assert.ok(matching(v056, '.nfc-app-main .nfc-page-header-copy',
    '@media (max-width: 767px)').some(rule =>
    rule.declarations.get('flex') === '0 1 auto'));

  const imports = read('src/main.tsx');
  const early = imports.indexOf("import './styles/v054-premium-system.css';");
  const middle = imports.indexOf("import './styles/v055-workspace-breathing.css';");
  const late = imports.indexOf("import './styles/v056-right-workspace-v2.css';");
  assert.ok(early >= 0 && early < middle && middle < late,
    'Unmodified v054/v055/v056 cascade order');
  assert.match(old054, /@media \(prefers-reduced-transparency: reduce\)/);
  assert.match(old054, /@media \(prefers-reduced-motion: reduce\)/);
});


test('v054-v056: 10 panel, media, root and workflow shadows remain retired', () => {
  // Unconditional exact single-selector and exact-property matches only.
  // Different selector groups, @media wrappers, shorthands, and !important
  // declarations are not used to infer additional safe removals.
  const panel = matching(v054, '.nfc-app-main .nfc-data-panel-header');
  const finalPanel = matching(v056, '.nfc-app-main .nfc-data-panel-header');
  assert.equal(panel.length, 1);
  assert.equal(finalPanel.length, 1);
  assert.deepEqual([...panel[0].declarations], [
    ['gap', '14px'],
    ['border-bottom-color', 'var(--nfc-v54-line)'],
  ], 'Independent historical panel gap and border-bottom color retained');
  for (const [name, value] of Object.entries({
    'min-height': '0',
    padding: 'var(--nfc-w2-panel-header-top) var(--nfc-w2-panel-header-x) var(--nfc-w2-panel-header-bottom)',
    background: 'transparent',
  })) {
    assert.equal(panel[0].declarations.has(name), false);
    assert.equal(finalPanel[0].declarations.get(name), value);
    assert.ok(!value.includes('!important'));
  }
  assert.equal(finalPanel[0].declarations.get('border'), '0');
  assert.equal(matching(v054, '.nfc-app-main .nfc-data-panel-header',
    '@media (max-width: 767px)')[0].declarations.get('min-height'), '58px');
  assert.equal(matching(v054, '.nfc-app-main .nfc-data-panel-header',
    '@media (max-width: 767px)')[0].declarations.get('padding'), '12px');
  assert.equal(matching(v056, '.nfc-app-main .nfc-data-panel-header',
    '@media (max-width: 767px)')[0].declarations.get('padding'), '13px 14px 11px');

  assert.equal(matching(v054, '.nfc-app-main .nfc-media-page .nfc-page-alert').length, 0);
  const media = matching(v056, '.nfc-app-main .nfc-media-page .nfc-page-alert');
  assert.equal(media.length, 2);
  assert.equal(media[0].declarations.get('margin'), '12px 14px 14px');
  assert.equal(media[1].declarations.has('margin'), false);
  assert.equal(media[1].declarations.get('border'), '0');
  assert.equal(media[1].declarations.get('background'),
    'color-mix(in srgb, var(--nfc-w2-warning) 6%, var(--nfc-w2-surface-soft))');

  const label = matching(v054, '.nfc-app-main .nfc-root-list-label');
  const finalLabel = matching(v056, '.nfc-app-main .nfc-root-list-label');
  assert.equal(label.length, 1);
  assert.equal(finalLabel.length, 1);
  assert.deepEqual([...label[0].declarations], [
    ['font-weight', '720'], ['letter-spacing', '0.06em'], ['text-transform', 'uppercase'],
  ], 'Independent label font weight, tracking and capitalization retained');
  assert.equal(finalLabel[0].declarations.get('color'), 'var(--nfc-w2-text-subtle)');
  assert.equal(finalLabel[0].declarations.get('font-size'), '11px');

  assert.equal(matching(v054, '.nfc-app-main .nfc-workflow-editor-layout').length, 0);
  assert.equal(matching(v056, '.nfc-app-main .nfc-workflow-editor-layout').length, 1);
  assert.equal(matching(v056, '.nfc-app-main .nfc-workflow-editor-layout')[0]
    .declarations.get('gap'), '28px');
  assert.equal(matching(v054, '.nfc-app-main .nfc-workflow-editor-layout',
    '@media (max-width: 980px)')[0].declarations.get('gap'), '16px',
    'Distinct 980px workflow rule must remain in original context');

  const option = matching(v054, '.nfc-app-main .nfc-workflow-mode-option');
  const finalOption = matching(v056, '.nfc-app-main .nfc-workflow-mode-option');
  assert.equal(option.length, 1);
  assert.equal(finalOption.length, 1);
  assert.deepEqual([...option[0].declarations], [
    ['padding', '10px 11px'], ['border', '1px solid var(--nfc-v54-line)'],
  ], 'Historical padding and border shorthand are independent of final border-color');
  for (const [name, value] of Object.entries({
    'min-height': '76px',
    'border-radius': 'var(--nfc-w2-radius-sm)',
    background: 'var(--nfc-w2-surface-soft)',
  })) {
    assert.equal(option[0].declarations.has(name), false);
    assert.equal(finalOption[0].declarations.get(name), value);
    assert.ok(!value.includes('!important'));
  }
  assert.equal(finalOption[0].declarations.get('border-color'), 'var(--nfc-w2-hairline)');
  assert.equal(matching(v054, '.nfc-app-main .nfc-workflow-mode-grid',
    '@media (max-width: 420px)')[0].declarations.get('grid-template-columns'),
    '1fr !important', 'Independent phone grid and priority must survive');

  assert.equal(3 + 1 + 2 + 1 + 3, 10);
  const imports = read('src/main.tsx');
  const early = imports.indexOf("import './styles/v054-premium-system.css';");
  const middle = imports.indexOf("import './styles/v055-workspace-breathing.css';");
  const late = imports.indexOf("import './styles/v056-right-workspace-v2.css';");
  assert.ok(early >= 0 && early < middle && middle < late);
  assert.match(old054, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old054, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v048-detail to v056: 11 description item shadows remain retired', () => {
  // Unconditional, exact single-selector and property matches with normal
  // priority. The earlier unique border, tracking, line-height and responsive
  // rule bodies must remain exactly owned by v048-detail.
  const cases = [
    ['.nfc-description-item', {
      'min-height': '78px',
      padding: '14px 16px',
    }, {
      'border-right': '1px solid var(--nfc-premium-line)',
      'border-bottom': '1px solid var(--nfc-premium-line)',
      background: 'transparent',
    }],
    ['.nfc-description-item dt', {
      'margin-bottom': '7px',
      color: 'var(--nfc-w2-text-subtle)',
      'font-size': '11px',
      'font-weight': '620',
    }, {
      'letter-spacing': '0.025em',
    }],
    ['.nfc-description-item dd', {
      color: 'var(--nfc-w2-text-muted)',
      'font-size': '12.5px',
    }, {
      'line-height': '1.5',
    }],
    ['.nfc-description-item dd.nfc-description-emphasis', {
      color: 'var(--nfc-w2-text)',
      'font-size': '14px',
      'font-weight': '650',
    }, {
      'letter-spacing': '-0.018em',
    }],
  ];
  let retired = 0;
  for (const [selector, winners, independent] of cases) {
    const previous = matching(v048, selector);
    const final = matching(v056, selector);
    assert.equal(previous.length, 1, selector + ': one unconditional historical rule');
    assert.equal(final.length, 1, selector + ': one unconditional final v056 owner');
    assert.deepEqual([...previous[0].declarations], Object.entries(independent),
      selector + ': preserve only independently owned v048 properties');
    for (const [name, expected] of Object.entries(winners)) {
      assert.equal(previous[0].declarations.has(name), false,
        selector + ': shadowed v048 property returned: ' + name);
      assert.equal(final[0].declarations.get(name), expected,
        selector + ': v056 authoritative property drifted: ' + name);
      assert.ok(!expected.includes('!important'), 'No importance escalation');
      retired++;
    }
  }
  assert.equal(retired, 11);

  // Preserve distinct v048 phone geometry and the more specific item state
  // selectors. Never flatten @media into an unconditional rule.
  const tablet = '@media (max-width: 1199px)';
  const phone = '@media (max-width: 767px)';
  const narrow = '@media (max-width: 420px)';
  assert.equal(matching(v048, '.nfc-page-header-copy', tablet)[0]
    .declarations.get('max-width'), 'min(760px, 68vw)');
  assert.equal(matching(v048, '.nfc-description-item', phone)[0]
    .declarations.get('min-height'), '70px');
  assert.equal(matching(v048, '.nfc-description-item', phone)[0]
    .declarations.get('padding'), '12px');
  assert.equal(matching(v048, '.nfc-description-item', phone)[0]
    .declarations.get('border-right'), '1px solid var(--nfc-premium-line)');
  assert.equal(matching(v048, '.nfc-description-item:nth-child(2n)', phone)[0]
    .declarations.get('border-right'), '0');
  assert.equal(matching(v048,
    '.nfc-description-item,\n  .nfc-description-item:nth-child(2n),\n  .nfc-description-item:nth-child(3n)',
    narrow)[0].declarations.get('min-height'), '64px');
  assert.equal(matching(v048, '.nfc-description-item:last-child', narrow)[0]
    .declarations.get('border-bottom'), '0');
  assert.equal(matching(v048, '.nfc-row-actions:focus-within')[0]
    .declarations.get('opacity'), '1');
  const imports = read('src/main.tsx');
  assert.ok(imports.indexOf("import './styles/v048-detail.css';") <
    imports.indexOf("import './styles/v049-workspace.css';"));
  assert.ok(imports.indexOf("import './styles/v049-workspace.css';") <
    imports.indexOf("import './styles/v056-right-workspace-v2.css';"));
  assert.match(old048, /@media \(prefers-reduced-motion: reduce\)/);
});


test('v049 to v056: 8 dashboard and form desktop shadows stay retired', () => {
  // Same single selector + property + unconditional context + normal priority.
  // Do not flatten responsive wrappers or confuse equal-specificity
  // declarations with later, more-specific Dashboard rail overrides.
  const cases = [
    ['.nfc-dashboard-page .nfc-dashboard-layout', {
      'margin-top': '24px',
      'grid-template-columns': 'minmax(0, 1fr) minmax(300px, 340px)',
      gap: '30px',
    }],
    ['.nfc-dashboard-page .nfc-dashboard-main-column', {
      gap: '26px',
    }],
    ['.nfc-dashboard-page .nfc-dashboard-rail', {
      position: 'sticky',
      top: '76px',
      gap: '22px',
    }],
    ['.nfc-form-grid', {
      gap: '16px 22px',
    }],
  ];
  let retired = 0;
  for (const [selector, expected] of cases) {
    assert.equal(matching(v049, selector).length, 0,
      'Old unconditional single-selector block must stay retired: ' + selector);
    const later = matching(v056, selector);
    assert.equal(later.length, 1, 'Expected one same-selector v056 owner: ' + selector);
    for (const [property, value] of Object.entries(expected)) {
      assert.equal(later[0].declarations.get(property), value,
        'v056 same-selector owner changed: ' + selector + ' ' + property);
      assert.ok(!value.includes('!important'), 'No priority difference permitted');
      retired += 1;
    }
  }
  assert.equal(retired, 8);

  // Independent surface ownership: the rail's !important card styling is
  // unrelated, while stronger v056 rail selectors override geometry as before.
  const railCard = matching(v049,
    '.nfc-dashboard-page .nfc-dashboard-rail > .nfc-data-panel');
  assert.equal(railCard.length, 1);
  assert.equal(railCard[0].declarations.get('border'),
    '1px solid var(--nfc-v49-line) !important');
  assert.equal(railCard[0].declarations.get('background'),
    'color-mix(in srgb, var(--nfc-v49-surface) 76%, transparent) !important');
  const strongerRail = matching(v056,
    '.nfc-app-main .nfc-dashboard-page .nfc-dashboard-rail');
  assert.equal(strongerRail.length, 2);
  assert.equal(strongerRail[0].declarations.get('gap'), '14px');
  assert.equal(strongerRail[1].declarations.get('position'), 'static');

  // The media rules intentionally remain in their ORIGINAL at-rule contexts;
  // moving them would change desktop and mobile computed styles.
  const wide = matching(v049, '.nfc-dashboard-page .nfc-dashboard-layout',
    '@media (min-width: 1600px)');
  assert.equal(wide.length, 1);
  assert.equal(wide[0].declarations.get('gap'), '24px');
  const tabletLayout = matching(v049, '.nfc-dashboard-page .nfc-dashboard-layout',
    '@media (max-width: 1199px)');
  assert.equal(tabletLayout[0].declarations.get('grid-template-columns'), '1fr');
  const tabletRail = matching(v049, '.nfc-dashboard-page .nfc-dashboard-rail',
    '@media (max-width: 1199px)');
  assert.equal(tabletRail[0].declarations.get('position'), 'static');
  assert.equal(tabletRail[0].declarations.get('grid-template-columns'),
    'repeat(2, minmax(0, 1fr))');
  const mobileGroup = matching(v049, [
    '.nfc-dashboard-page .nfc-dashboard-layout',
    '.nfc-dashboard-page .nfc-dashboard-main-column',
    '.nfc-dashboard-page .nfc-dashboard-rail',
  ].join(',\n  '), '@media (max-width: 767px)');
  assert.equal(mobileGroup.length, 1);
  assert.equal(mobileGroup[0].declarations.get('gap'), '12px');
  assert.equal(matching(v049, '.nfc-dashboard-page .nfc-dashboard-rail',
    '@media (max-width: 767px)')[0].declarations.get('grid-template-columns'), '1fr');

  const imports = read('src/main.tsx');
  const early = imports.indexOf("import './styles/v049-workspace.css';");
  const middle = imports.indexOf("import './styles/v055-workspace-breathing.css';");
  const late = imports.indexOf("import './styles/v056-right-workspace-v2.css';");
  assert.ok(early >= 0 && early < middle && middle < late,
    'Identical source-order cascade required');
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v049 -> v056: 9 exact v049 page and panel typography shadows remain retired', () => {
  // These five old unconditional blocks contained only normal-priority
  // declarations overridden by exactly matching later v056 selectors.
  // The second v049 blocks below are independently meaningful and remain.
  const cases = [
    ['.nfc-page-title', {
      color: 'var(--nfc-w2-text)',
      'line-height': '1.18',
      'letter-spacing': '-0.014em',
    }, {
      'font-size': 'clamp(25px, 1.85vw, 32px)',
      'font-weight': '660',
    }],
    ['.nfc-page-description', {
      'max-width': '82ch',
      color: 'var(--nfc-w2-text-muted)',
    }, {
      'margin-top': '7px',
      'font-size': '11.5px',
      'line-height': '1.62',
    }],
    ['.nfc-data-panel-header', {
      gap: '18px',
    }, {
      'min-height': '62px',
      padding: '15px 18px 14px',
      'border-bottom-color': 'var(--nfc-border-soft)',
    }],
    ['.nfc-data-panel-title', {
      color: 'var(--nfc-w2-text)',
      'letter-spacing': '-0.004em',
    }, {
      'font-size': '13px',
      'font-weight': '670',
    }],
    ['.nfc-data-panel-description', {
      color: 'var(--nfc-w2-text-subtle)',
    }, {
      'margin-top': '4px',
      'font-size': '10.5px',
      'line-height': '1.52',
    }],
  ];
  let removed = 0;
  for (const [selector, shadows, independent] of cases) {
    const historical = matching(v049, selector);
    const canonical = matching(v056, selector);
    assert.equal(historical.length, 1,
      'Only the independent later v049 owner must remain: ' + selector);
    assert.equal(canonical.length, 1,
      'Exactly one unconditional canonical v056 owner: ' + selector);
    for (const [property, value] of Object.entries(shadows)) {
      assert.equal(historical[0].declarations.has(property), false,
        'Obsolete v049 property reintroduced: ' + selector + ' ' + property);
      assert.equal(canonical[0].declarations.get(property), value,
        'Exact same-selector v056 authority changed: ' + selector + ' ' + property);
      assert.ok(!value.includes('!important'),
        'Normal priority preserved: ' + selector + ' ' + property);
      removed++;
    }
    for (const [property, value] of Object.entries(independent)) {
      assert.equal(historical[0].declarations.get(property), value,
        'Independent v049 rule must not be removed: ' + selector + ' ' + property);
    }
  }
  assert.equal(removed, 9);

  // Keep the independently meaningful high-specificity theme/title layer,
  // phone/tablet CSS and status/keyboard/reduced-motion safeguards.
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-title')[0]
    .declarations.get('color'), 'var(--nfc-text)');
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-description')[0]
    .declarations.get('color'), 'var(--nfc-text-muted)');
  assert.equal(matching(v049, '.nfc-page-title',
    '@media (max-width: 767px)')[0].declarations.get('font-size'), '22px');
  assert.equal(matching(v049, '.nfc-page-description',
    '@media (max-width: 767px)')[0].declarations.get('font-size'), '11px');
  assert.equal(matching(v049, '.nfc-data-panel-header',
    '@media (max-width: 767px)')[0].declarations.get('min-height'), '56px');
  assert.equal(matching(v049, '.nfc-data-panel-description',
    '@media (max-width: 767px)')[0].declarations.get('display'), 'block');
  assert.equal(matching(v049, '.nfc-row-actions:focus-within')[0]
    .declarations.get('opacity'), '1');
  const entry = read('src/main.tsx');
  const early = entry.indexOf("import './styles/v049-workspace.css';");
  const mid = entry.indexOf("import './styles/v054-premium-system.css';");
  const late = entry.indexOf("import './styles/v056-right-workspace-v2.css';");
  assert.ok(early >= 0 && early < mid && mid < late);
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
});


test('v054 → v055/v056: 4 header, eyebrow and action-bar shadows retired', () => {
  // Exact ungrouped selector, unconditional context, normal importance,
  // and strictly later import sequence. Preserve all other declarations.
  const eyebrow = matching(v054, '.nfc-app-main .nfc-page-eyebrow');
  const laterEyebrow = matching(v055, '.nfc-app-main .nfc-page-eyebrow');
  const finalEyebrow = matching(v056, '.nfc-app-main .nfc-page-eyebrow');
  assert.equal(eyebrow.length, 1);
  assert.equal(laterEyebrow.length, 1);
  assert.equal(finalEyebrow.length, 1);
  assert.deepEqual([...eyebrow[0].declarations], [
    ['align-items', 'center'],
    ['gap', '7px'],
    ['color', 'var(--nfc-text-subtle)'],
    ['font-size', '9px'],
    ['font-weight', '760'],
    ['letter-spacing', '0.14em'],
  ], 'Keep six independent historical eyebrow properties');
  assert.equal(eyebrow[0].declarations.has('display'), false);
  assert.equal(eyebrow[0].declarations.has('margin-bottom'), false);
  assert.equal(laterEyebrow[0].declarations.get('margin-bottom'), '10px');
  assert.equal(finalEyebrow[0].declarations.get('display'), 'none');
  assert.equal(matching(v054, '.nfc-app-main .nfc-page-eyebrow::before')[0]
    .declarations.get('content'), "''", 'Original ornamental pseudo-element unchanged');

  const action = '.nfc-app-main .nfc-page-actions .nfc-action-bar';
  assert.equal(matching(v054, action).length, 0,
    'Completely shadowed v054 action gap block cannot be reintroduced');
  const laterAction = matching(v055, action);
  assert.equal(laterAction.length, 1);
  assert.equal(laterAction[0].declarations.get('gap'), '9px');
  assert.equal(laterAction[0].declarations.get('justify-content'), 'flex-end');

  const header = matching(v054, '.nfc-header.nfc-header');
  const finalHeader = matching(v056, '.nfc-header.nfc-header');
  assert.equal(header.length, 1);
  assert.equal(finalHeader.length, 1);
  assert.deepEqual([...header[0].declarations], [
    ['padding-top', '10px'],
    ['padding-bottom', '9px'],
    ['border-bottom-color',
      'color-mix(in srgb, var(--nfc-border-soft) 88%, transparent)'],
  ], 'Keep historical header spacing and border color');
  assert.equal(header[0].declarations.has('min-height'), false);
  assert.equal(finalHeader[0].declarations.get('min-height'), '68px');
  assert.equal(matching(v054, '.nfc-header.nfc-header',
    '@media (max-width: 767px)')[0].declarations.get('min-height'),
    '54px', 'Preserve distinct 767px header behavior');
  assert.match(old054, /@media \(prefers-reduced-transparency: reduce\)/);
  assert.equal(matching(v054, '.nfc-header.nfc-header',
    '@media (prefers-reduced-transparency: reduce)')[0]
    .declarations.get('backdrop-filter'), 'none !important');

  const imports = read('src/main.tsx');
  const indexes = [
    "import './styles/v054-premium-system.css';",
    "import './styles/v055-workspace-breathing.css';",
    "import './styles/v056-right-workspace-v2.css';",
  ].map(value => imports.indexOf(value));
  assert.ok(indexes[0] >= 0 && indexes[0] < indexes[1]
    && indexes[1] < indexes[2], 'CSS cascade load order must not change');
  assert.equal(2 + 1 + 1, 4);
});


test('v049 → v056: eight metric-card geometry, surface and hover shadows stay retired', () => {
  const retired = [
    ['.nfc-metric-card', {
      'min-height': '104px',
      padding: '16px 17px',
      'border-radius': 'var(--nfc-w2-radius-md)',
      background: 'color-mix(in srgb, var(--nfc-w2-surface) 88%, var(--nfc-w2-surface-soft))',
      'box-shadow': 'none',
    }],
    ['.nfc-metric-card:hover', {
      transform: 'none',
      'border-color': 'var(--nfc-w2-hairline-strong)',
      background: 'var(--nfc-w2-surface)',
    }],
  ];
  let total = 0;
  for (const [selector, declarations] of retired) {
    const previous = matching(v049, selector);
    const owner = matching(v056, selector);
    assert.equal(owner.length, 1, 'Exactly one unconditional v056 metric owner: ' + selector);
    for (const [property, value] of Object.entries(declarations)) {
      assert.ok(previous.every(rule => !rule.declarations.has(property)),
        'v049 exact-selector metric shadow reintroduced: ' + selector + ' / ' + property);
      assert.equal(owner[0].declarations.get(property), value,
        'v056 metric owner changed: ' + selector + ' / ' + property);
      assert.ok(!value.includes('!important'), 'No importance escalation: ' + property);
      total += 1;
    }
  }
  assert.equal(total, 8);
  const nativeCard = matching(v049, '.nfc-metric-card');
  assert.equal(nativeCard.length, 2, 'Retain independent early border and late transition');
  assert.equal(nativeCard[1].declarations.get('border'),
    '1px solid var(--nfc-border-soft)');
  assert.equal(nativeCard[1].declarations.get('transition'),
    'transform 150ms ease,\n    border-color 150ms ease,\n    box-shadow 150ms ease,\n    background 150ms ease');
  assert.equal(matching(v049, '.nfc-metric-card:hover')[0].declarations.get('box-shadow'),
    '0 1px 1px color-mix(in srgb, var(--nfc-text) 3%, transparent),\n    0 14px 34px color-mix(in srgb, var(--nfc-text) 7%, transparent)');
  assert.equal(matching(v049, '.nfc-metric-card', '@media (max-width: 767px)')[0]
    .declarations.get('min-height'), '94px', 'Separate phone min-height must remain');
  assert.equal(matching(v049, '.nfc-metric-card', '@media (max-width: 767px)')[0]
    .declarations.get('padding'), '12px 13px', 'Separate phone padding must remain');
  assert.match(old049, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(old049, /@media \(prefers-reduced-transparency: reduce\)/);
  const entry = read('src/main.tsx');
  assert.ok(entry.indexOf("./styles/v049-workspace.css") <
    entry.indexOf("./styles/v056-right-workspace-v2.css"),
  'The exact cross-layer import order must remain unchanged');
});

test('v050-v051: 32 exact-context cross-file historical shadows remain retired', () => {
  // Same unconditional selector, same property and normal importance.
  // Later v054/v056 rules win; earlier independent declarations still work.
  const earlyFiles = {
    f050: leafRules(read('src/styles/v050-layout.css')),
    f051: leafRules(read('src/styles/v051-product-polish.css')),
  };
  const owners = {
    v054: leafRules(read('src/styles/v054-premium-system.css')),
    v056: leafRules(read('src/styles/v056-right-workspace-v2.css')),
  };
  const shadows = [
  [
    "f050",
    ".nfc-dashboard-page .nfc-dashboard-layout",
    [
      "margin-top",
      "grid-template-columns",
      "gap"
    ],
    "v056"
  ],
  [
    "f050",
    ".nfc-dashboard-page .nfc-dashboard-main-column",
    [
      "gap"
    ],
    "v056"
  ],
  [
    "f050",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    [
      "position",
      "top",
      "gap"
    ],
    "v056"
  ],
  [
    "f050",
    ".nfc-dashboard-page .nfc-quick-action",
    [
      "min-height",
      "padding"
    ],
    "v056"
  ],
  [
    "f050",
    ".nfc-dashboard-page .nfc-summary-row",
    [
      "min-height",
      "padding-inline"
    ],
    "v056"
  ],
  [
    "f051",
    ".nfc-row-actions",
    [
      "gap",
      "opacity"
    ],
    "v056"
  ],
  [
    "f051",
    ".nfc-row-actions:focus-within",
    [
      "opacity"
    ],
    "v056"
  ],
  [
    "f051",
    ".nfc-drawer-title",
    [
      "min-width"
    ],
    "v054"
  ],
  [
    "f051",
    ".nfc-drawer-title-kicker",
    [
      "color",
      "font-size",
      "font-weight",
      "letter-spacing",
      "text-transform"
    ],
    "v054"
  ],
  [
    "f051",
    ".nfc-drawer-title-row",
    [
      "min-width",
      "display",
      "align-items",
      "gap"
    ],
    "v054"
  ],
  [
    "f051",
    ".nfc-overlay-stack",
    [
      "display",
      "gap"
    ],
    "v054"
  ],
  [
    "f051",
    ".nfc-overlay-section",
    [
      "overflow"
    ],
    "v054"
  ],
  [
    "f051",
    ".nfc-overlay-section-header",
    [
      "min-height",
      "padding"
    ],
    "v054"
  ],
  [
    "f051",
    ".nfc-code-block",
    [
      "border",
      "border-radius",
      "background"
    ],
    "v054"
  ]
];
  const retained = new Map([
    ['.nfc-dashboard-page .nfc-dashboard-layout', ['align-items', 'start']],
    ['.nfc-dashboard-page .nfc-quick-action', ['border-radius', '12px']],
    ['.nfc-dashboard-page .nfc-summary-row', ['border-bottom-style', 'dashed']],
    ['.nfc-row-actions', ['transition', 'opacity 140ms ease, transform 140ms ease']],
    ['.nfc-drawer-title-kicker', ['margin-bottom', '4px']],
    ['.nfc-drawer-title-row', ['font-weight', '680']],
  ]);
  let retired = 0;
  for (const [file, selector, properties, owner] of shadows) {
    const previous = matching(earlyFiles[file], selector);
    const later = matching(owners[owner], selector);
    assert.ok(later.length >= 1, 'Missing authoritative winner: ' + selector);
    for (const property of properties) {
      assert.ok(previous.every(rule => !rule.declarations.has(property)),
        'Retired historical declaration returned: ' + selector + '/' + property);
      assert.ok(later.some(rule => rule.declarations.has(property)),
        'Final same-selector rule no longer owns ' + selector + '/' + property);
      retired++;
    }
    if (retained.has(selector)) {
      const [property, value] = retained.get(selector);
      assert.ok(previous.some(rule => rule.declarations.get(property) === value),
        'Independent historical declaration lost: ' + selector + '/' + property);
    } else {
      assert.equal(previous.length, 0,
        'Fully shadowed legacy selector must be retired: ' + selector);
    }
  }
  assert.equal(retired, 32);
  const entry = read('src/main.tsx');
  const imports = [
    "import './styles/v050-layout.css';",
    "import './styles/v051-product-polish.css';",
    "import './styles/v054-premium-system.css';",
    "import './styles/v056-right-workspace-v2.css';",
    "import './styles/console-v2.css';",
  ];
  for (let i = 1; i < imports.length; i++) {
    assert.ok(entry.indexOf(imports[i-1]) < entry.indexOf(imports[i]),
      'Exact cascade import order changed: ' + imports[i]);
  }
  // Do not weaken the 8-width/4-theme actual Chromium evidence.
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  for (const gate of ['browser-workspace-cascade.mjs',
    'browser-full-route-visual.mjs','browser-overlay-smoke.mjs']) {
    assert.ok(ci.includes(gate), 'Missing latest-head browser evidence: ' + gate);
  }
});

test('v048 base: 112 earlier cross-layer shadows retired with final owners preserved', () => {
  const early = leafRules(read('src/styles/v048.css'));
  const final = ['v048-detail.css', 'v049-workspace.css',
    'v054-premium-system.css', 'v056-right-workspace-v2.css']
    .map(f => ({file:f, rules:leafRules(read('src/styles/' + f))}));
  const cases = [
  [
    ".nfc-header.nfc-header",
    [
      "position",
      "top",
      "z-index",
      "min-height",
      "margin",
      "padding",
      "border",
      "border-bottom",
      "border-radius",
      "background",
      "box-shadow",
      "backdrop-filter",
      "-webkit-backdrop-filter"
    ],
    [],
    [
      "v048-detail.css",
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-header-left",
    [
      "gap"
    ],
    [
      [
        "min-width",
        "0"
      ]
    ],
    [
      "v049-workspace.css"
    ]
  ],
  [
    ".nfc-header-workspace",
    [
      "min-width",
      "padding",
      "border-right"
    ],
    [],
    [
      "v049-workspace.css"
    ]
  ],
  [
    ".nfc-header-workspace-kicker",
    [
      "color",
      "font-size",
      "font-weight",
      "letter-spacing"
    ],
    [
      [
        "display",
        "block"
      ],
      [
        "line-height",
        "1.1"
      ]
    ],
    [
      "v049-workspace.css",
      "v054-premium-system.css"
    ]
  ],
  [
    ".nfc-header-workspace-name",
    [
      "margin-top",
      "color",
      "font-size",
      "font-weight"
    ],
    [
      [
        "display",
        "block"
      ],
      [
        "line-height",
        "1.15"
      ]
    ],
    [
      "v049-workspace.css",
      "v054-premium-system.css"
    ]
  ],
  [
    ".nfc-header-status",
    [
      "gap"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-header-command-cluster",
    [
      "display",
      "align-items",
      "gap"
    ],
    [],
    [
      "v048-detail.css",
      "v054-premium-system.css"
    ]
  ],
  [
    ".nfc-header-action-label",
    [
      "color",
      "font-size"
    ],
    [
      [
        "margin-left",
        "5px"
      ]
    ],
    [
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-page-content",
    [
      "position",
      "z-index",
      "width",
      "padding"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-page-content > *",
    [
      "width",
      "margin-inline"
    ],
    [],
    [
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-page-header",
    [
      "min-height",
      "margin",
      "padding",
      "align-items",
      "gap",
      "border",
      "border-bottom",
      "border-radius",
      "background",
      "box-shadow"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-page-eyebrow",
    [
      "margin-bottom",
      "color",
      "font-size",
      "font-weight",
      "letter-spacing",
      "text-transform"
    ],
    [],
    [
      "v049-workspace.css"
    ]
  ],
  [
    ".nfc-page-title",
    [
      "color",
      "font-size",
      "font-weight",
      "line-height",
      "letter-spacing"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-page-description",
    [
      "max-width",
      "margin-top",
      "color",
      "font-size",
      "line-height"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-page-actions",
    [
      "align-self",
      "gap",
      "padding-bottom"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-data-panel",
    [
      "overflow"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-data-panel-header",
    [
      "min-height",
      "padding"
    ],
    [
      [
        "border-bottom",
        "1px solid var(--nfc-premium-line)"
      ],
      [
        "background",
        "transparent !important"
      ]
    ],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-data-panel-title",
    [
      "color",
      "font-size",
      "font-weight",
      "letter-spacing"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-data-panel-description",
    [
      "margin-top",
      "color",
      "font-size",
      "line-height"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-panel-count",
    [
      "color",
      "font-size",
      "font-weight",
      "letter-spacing"
    ],
    [],
    [
      "v049-workspace.css"
    ]
  ],
  [
    ".nfc-metric-grid",
    [
      "gap",
      "overflow",
      "border",
      "border-radius",
      "background",
      "box-shadow"
    ],
    [],
    [
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-metric-card",
    [
      "min-height",
      "padding",
      "border",
      "border-right",
      "border-radius",
      "background",
      "box-shadow"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-metric-label",
    [
      "color",
      "font-size",
      "font-weight",
      "letter-spacing",
      "text-transform"
    ],
    [],
    [
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-metric-value",
    [
      "margin-top",
      "color",
      "font-size",
      "font-weight",
      "letter-spacing"
    ],
    [],
    [
      "v049-workspace.css",
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-metric-meta",
    [
      "margin-top",
      "color",
      "font-size"
    ],
    [],
    [
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-filter-control",
    [
      "color",
      "font-size",
      "font-weight"
    ],
    [],
    [
      "v056-right-workspace-v2.css"
    ]
  ],
  [
    ".nfc-mobile-pagination",
    [
      "border-top-color",
      "background"
    ],
    [],
    [
      "v048-detail.css",
      "v049-workspace.css"
    ]
  ]
];
  let removed = 0;
  for (const [selector, deleted, independent, owners] of cases) {
    const old = matching(early, selector);
    if (independent.length === 0) {
      assert.equal(old.length, 0, selector + ': shadowed empty rule returned');
    } else {
      assert.equal(old.length, 1, selector + ': independent rule lost');
      for (const [key, value] of independent) {
        assert.equal(old[0].declarations.get(key), value,
          selector + ': retained independent property ' + key);
      }
    }
    for (const property of deleted) {
      assert.ok(old.every(rule => !rule.declarations.has(property)),
        selector + ': retired v048 declaration returned ' + property);
      assert.ok(owners.some(f => final.some(entry => entry.file === f &&
        matching(entry.rules, selector).some(rule => rule.declarations.has(property)))),
        selector + ': late owner missing for ' + property);
      removed++;
    }
  }
  assert.equal(removed, 112);
  assert.equal(cases.length, 27);
  const src = read('src/styles/v048.css');
  for (const marker of [':root {', "[data-theme='dark'] {",
    '--nfc-premium-control: 38px', '@media (max-width: 767px)',
    '@media (prefers-reduced-motion: reduce)']) {
    assert.ok(src.includes(marker), 'Theme or responsive property lost: ' + marker);
  }
  const entry = read('src/main.tsx');
  const order = ['v048.css','v048-detail.css','v049-workspace.css',
    'v054-premium-system.css','v056-right-workspace-v2.css','console-v2.css'];
  for (let i=1;i<order.length;i++) assert.ok(
    entry.indexOf("import './styles/" + order[i-1] + "';") <
      entry.indexOf("import './styles/" + order[i] + "';"),
    'Original CSS import precedence changed at ' + order[i]);
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  for (const runner of ['browser-full-route-visual.mjs',
    'browser-workspace-cascade.mjs', 'browser-overlay-smoke.mjs']) {
    assert.ok(ci.includes(runner), 'Full read-only Chromium evidence lost ' + runner);
  }
});
