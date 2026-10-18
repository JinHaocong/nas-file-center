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
const old054 = read('src/styles/v054-premium-system.css');
const old056 = read('src/styles/v056-right-workspace-v2.css');
const v049 = leafRules(old049);
const v054 = leafRules(old054);
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

test('v049 dashboard layout and important native rail remain independently owned', () => {
  const layout = matching(v049, '.nfc-dashboard-page .nfc-dashboard-layout');
  assert.equal(layout.length, 1);
  assert.equal(layout[0].declarations.get('margin-top'), '18px');
  assert.equal(layout[0].declarations.get('gap'), '22px');
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
