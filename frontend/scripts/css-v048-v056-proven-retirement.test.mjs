import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = name => readFileSync(resolve(process.cwd(), name), 'utf8');
const earlier = read('src/styles/v048.css');
const later = read('src/styles/v056-right-workspace-v2.css');
const cases = [
  [
    "",
    "body, .nfc-app-shell, .nfc-app-main",
    "background",
    "var(--nfc-w2-canvas)"
  ],
  [
    "",
    ".nfc-metric-card:last-child",
    "border-right",
    "1px solid var(--nfc-w2-hairline)"
  ],
  [
    "",
    ".nfc-metric-card:hover",
    "transform",
    "none"
  ],
  [
    "",
    ".nfc-metric-card:hover",
    "background",
    "var(--nfc-w2-surface)"
  ],
  [
    "",
    ".nfc-table-link, .nfc-plan-name, .nfc-mobile-record-title",
    "color",
    "var(--nfc-w2-text)"
  ],
  [
    "",
    ".nfc-table-link, .nfc-plan-name, .nfc-mobile-record-title",
    "font-weight",
    "610"
  ],
  [
    "",
    ".nfc-table-meta, .nfc-table-muted",
    "color",
    "var(--nfc-w2-text-subtle)"
  ],
  [
    "",
    ".nfc-worker-primary, .nfc-worker-identity",
    "border-right-color",
    "var(--nfc-w2-hairline)"
  ],
  [
    "@media (max-width: 1199px)",
    ".nfc-page-content",
    "padding-inline",
    "24px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-content",
    "padding",
    "18px 14px max(34px, env(safe-area-inset-bottom))"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "margin-bottom",
    "22px !important"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "padding-bottom",
    "18px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "align-items",
    "stretch"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "gap",
    "15px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-description",
    "font-size",
    "12.75px"
  ]
];

// Do not flatten @media boundaries, ignore CSS comments during selector
// lookup, and require the full grouped selector text to match its late owner.
function leafRules(css) {
  const rules = [], stack = [];
  let segmentStart = 0, comment = false, quote = null, escaped = false;
  for (let i = 0; i < css.length; i += 1) {
    const current = css[i], next = css[i + 1];
    if (comment) {
      if (current === '*' && next === '/') { comment = false; i += 1; }
      continue;
    }
    if (quote) {
      if (escaped) { escaped = false; continue; }
      if (current === '\\') { escaped = true; continue; }
      if (current === quote) quote = null;
      continue;
    }
    if (current === '/' && next === '*') { comment = true; i += 1; continue; }
    if (current === '"' || current === "'") { quote = current; continue; }
    if (current === '{') {
      const selector = css.slice(segmentStart, i)
        .replace(/\/\*[\s\S]*?\*\//g, '').trim().replace(/\s+/g, ' ');
      const context = stack.filter(x => x.selector.startsWith('@'))
        .map(x => x.selector).join(' > ');
      stack.push({ selector, context, bodyStart: i + 1 });
      segmentStart = i + 1;
    } else if (current === '}') {
      const node = stack.pop();
      assert.ok(node, 'CSS blocks must remain balanced');
      const body = css.slice(node.bodyStart, i);
      if (!node.selector.startsWith('@') && !body.includes('{')) {
        const declarations = new Map();
        for (const part of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = part.indexOf(':');
          if (colon > 0) declarations.set(part.slice(0, colon).trim(),
            part.slice(colon + 1).trim());
        }
        rules.push({ selector: node.selector, context: node.context, declarations });
      }
      segmentStart = i + 1;
    } else if (current === ';' && stack.length === 0) segmentStart = i + 1;
  }
  assert.equal(stack.length, 0, 'CSS @media groups must remain balanced');
  return rules;
}
const oldRules = leafRules(earlier), newRules = leafRules(later);
const owners = (rules, context, selector) =>
  rules.filter(x => x.context === context && x.selector === selector);

test('15 exact-selector, equal-at-rule v048 shadows stay retired with pinned v056 values', () => {
  assert.equal(cases.length, 15);
  assert.equal(new Set(cases.map(x => x.slice(0, 3).join('|'))).size, 15);
  for (const [context, selector, property, expected] of cases) {
    const label = [context, selector, property].join(' | ');
    assert.ok(owners(oldRules, context, selector).every(rule =>
      !rule.declarations.has(property)), 'Earlier property was reintroduced: ' + label);
    const winner = owners(newRules, context, selector)
      .filter(rule => rule.declarations.has(property));
    assert.ok(winner.length, 'Exact later property owner disappeared: ' + label);
    assert.equal(winner.at(-1).declarations.get(property), expected,
      'Later effective authored declaration changed: ' + label);
  }
});

test('v048 keeps independent desktop/mobile, premium, hover and reduced-motion values', () => {
  for (const [context, selector, property, expected] of [
    ['', '.nfc-metric-card:hover', 'box-shadow', 'none'],
    ['', '.nfc-data-panel-header', 'background', 'transparent !important'],
    ['@media (max-width: 767px)', '.nfc-header.nfc-header', 'min-height', '54px'],
    ['@media (max-width: 767px)', '.nfc-page-header', 'min-height', 'auto'],
    ['@media (max-width: 767px)', '.nfc-metric-card', 'min-height', '102px'],
    ['@media (max-width: 767px)', '.nfc-metric-card', 'padding', '14px'],
    ['@media (max-width: 767px)', '.nfc-data-panel-description', 'display', 'none'],
  ]) assert.ok(owners(oldRules, context, selector).some(rule =>
    rule.declarations.get(property) === expected),
  'Independent early CSS must remain: ' + selector + ' ' + property);
  assert.match(earlier, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(earlier, /--nfc-premium-control: 38px/);
  assert.doesNotMatch(earlier, /^[ \t]+$/m,
    'Source removal must not introduce whitespace-only lines');
});

test('source order and exact-HEAD browser validation stay intact', () => {
  const main = read('src/main.tsx');
  const from = main.indexOf("import './styles/v048.css';");
  const to = main.indexOf("import './styles/v056-right-workspace-v2.css';");
  const native = main.indexOf("import './styles/console-v2.css';");
  assert.ok(from >= 0 && from < to && to < native, 'CSS ownership import order changed');
  const workflow = read('../.github/workflows/ui-v044-validation.yml');
  for (const runner of ['browser-full-route-visual.mjs',
    'browser-workspace-cascade.mjs', 'browser-overlay-smoke.mjs'])
    assert.ok(workflow.includes(runner), 'Read-only Chromium gate lost ' + runner);
});
