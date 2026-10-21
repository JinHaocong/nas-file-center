import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = name => readFileSync(resolve(process.cwd(), name), 'utf8');
const early = read('src/styles/v049-workspace.css');
const successor = read('src/styles/v056-right-workspace-v2.css');
const entries = [
  [
    "",
    "body, .nfc-app-shell, .nfc-app-main",
    "background",
    "var(--nfc-w2-canvas)"
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
    ".nfc-table-meta, .nfc-table-muted",
    "font-size",
    "11.5px"
  ],
  [
    "",
    ".nfc-worker-primary, .nfc-worker-identity",
    "min-height",
    "78px"
  ],
  [
    "",
    ".nfc-worker-primary, .nfc-worker-identity",
    "padding",
    "14px 16px"
  ],
  [
    "",
    ".nfc-worker-primary, .nfc-worker-identity",
    "border-right-color",
    "var(--nfc-w2-hairline)"
  ],
  [
    "",
    ".nfc-worker-eyebrow, .nfc-worker-stat > span, .nfc-worker-facts span",
    "color",
    "var(--nfc-w2-text-subtle)"
  ],
  [
    "",
    ".nfc-worker-eyebrow, .nfc-worker-stat > span, .nfc-worker-facts span",
    "font-size",
    "11px"
  ],
  [
    "",
    ".nfc-worker-stat > strong, .nfc-worker-facts strong",
    "color",
    "var(--nfc-w2-text)"
  ],
  [
    "",
    ".nfc-worker-stat > strong, .nfc-worker-facts strong",
    "font-size",
    "12.5px"
  ],
  [
    "",
    ".nfc-plan-detail-page .nfc-lifecycle-step, .nfc-scan-detail-page .nfc-lifecycle-step",
    "min-height",
    "66px"
  ],
  [
    "",
    ".nfc-plan-detail-page .nfc-lifecycle-step, .nfc-scan-detail-page .nfc-lifecycle-step",
    "padding",
    "11px 14px"
  ],
  [
    "",
    ".nfc-plan-detail-page .nfc-lifecycle-step, .nfc-scan-detail-page .nfc-lifecycle-step",
    "border-right-color",
    "var(--nfc-w2-hairline)"
  ],
  [
    "",
    ".nfc-quarantine-page .nfc-bulk-action-bar",
    "margin",
    "12px"
  ],
  [
    "",
    ".nfc-quarantine-page .nfc-bulk-action-bar",
    "border",
    "1px solid var(--nfc-w2-hairline) !important"
  ],
  [
    "",
    ".nfc-quarantine-page .nfc-bulk-action-bar",
    "background",
    "color-mix(in srgb, var(--nfc-w2-surface) 90%, transparent) !important"
  ],
  [
    "",
    ".nfc-login-shell",
    "padding",
    "clamp(20px, 4vw, 44px)"
  ],
  [
    "",
    ".nfc-login-panel",
    "width",
    "min(424px, 100%)"
  ],
  [
    "",
    ".nfc-login-panel",
    "padding",
    "28px"
  ],
  [
    "",
    ".nfc-metric-card:last-child",
    "border-right",
    "1px solid var(--nfc-w2-hairline)"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-actions, .nfc-page-actions .nfc-action-bar",
    "width",
    "100%"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-actions, .nfc-page-actions .nfc-action-bar",
    "justify-content",
    "flex-start"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-login-panel",
    "padding",
    "24px 20px"
  ]
];

function leafRules(css) {
  const rules = [], stack = [];
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
      const selector = css.slice(start, i).replace(/\/\*[\s\S]*?\*\//g, '')
        .trim().replace(/\s+/g, ' ');
      stack.push({ selector, from: i + 1, context: stack
        .filter(rule => rule.selector.startsWith('@'))
        .map(rule => rule.selector).join(' > ') });
      start = i + 1;
    } else if (ch === '}') {
      const entry = stack.pop();
      assert.ok(entry, 'Unbalanced CSS closing brace');
      const body = css.slice(entry.from, i);
      if (!entry.selector.startsWith('@') && !body.includes('{')) {
        const declarations = new Map();
        for (const part of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = part.indexOf(':');
          if (colon === -1) continue;
          declarations.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim());
        }
        rules.push({ selector: entry.selector, context: entry.context, declarations });
      }
      start = i + 1;
    } else if (ch === ';' && stack.length === 0) start = i + 1;
  }
  assert.equal(stack.length, 0, 'CSS import layers must stay balanced');
  return rules;
}

const earlier = leafRules(early), later = leafRules(successor);
const matches = (rules, selector, context) => rules.filter(rule =>
  rule.selector === selector && rule.context === context);

test('25 earlier v049 declarations stay retired with a same-context final v056 owner', () => {
  assert.equal(entries.length, 25);
  const unique = new Set(entries.map(([context, selector, property]) =>
    [context, selector, property].join('|')));
  assert.equal(unique.size, 25);
  for (const [context, selector, property, expected] of entries) {
    const key = [context, selector, property].join(' | ');
    assert.ok(matches(earlier, selector, context).every(rule =>
      !rule.declarations.has(property)), 'Shadowed v049 property returned: ' + key);
    const owner = matches(later, selector, context)
      .filter(rule => rule.declarations.has(property));
    assert.ok(owner.length > 0, 'Final v056 CSS owner missing: ' + key);
    assert.equal(owner.at(-1).declarations.get(property), expected,
      'Actual final v056 declaration changed, needs new visual evidence: ' + key);
  }
});

test('earlier important priorities and independent responsive owner remain protected', () => {
  const importantCases = [
    ['', '.nfc-header.nfc-header', 'border',
      '1px solid var(--nfc-border-soft) !important'],
    ['', '.nfc-header.nfc-header', 'background',
      'color-mix(in srgb, var(--nfc-nav-surface) 86%, transparent) !important'],
    ['@media (max-width: 767px)', '.nfc-header.nfc-header', 'border',
      '1px solid var(--nfc-border-soft) !important'],
    ['', '.nfc-overlay-section', 'border-radius',
      'var(--nfc-ui-inner-radius) !important'],
    ['', '.nfc-overlay-section', 'background',
      'var(--nfc-ui-panel-bg-strong) !important'],
  ];
  for (const [context, selector, property, value] of importantCases) {
    assert.ok(matches(earlier, selector, context)
      .some(rule => rule.declarations.get(property) === value),
    'Protected source importance barrier must not be silently retired: ' +
      selector + ' ' + property);
  }
  assert.ok(matches(earlier,
    '.nfc-filter-bar, .nfc-bulk-action-bar', '@media (max-width: 767px)')
    .some(rule => rule.declarations.get('padding') === '9px 10px'),
  'Older explicitly audited responsive toolbar padding stays preserved');
});

test('historical stylesheet precedence and readonly browser gates are unchanged', () => {
  const entry = read('src/main.tsx');
  const oldImport = entry.indexOf("import './styles/v049-workspace.css';");
  const newImport = entry.indexOf("import './styles/v056-right-workspace-v2.css';");
  const nativeImport = entry.indexOf("import './styles/console-v2.css';");
  assert.ok(oldImport >= 0 && oldImport < newImport && newImport < nativeImport);
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  for (const runner of [
    'browser-full-route-visual.mjs',
    'browser-workspace-cascade.mjs',
    'browser-overlay-smoke.mjs',
  ]) assert.ok(ci.includes(runner), 'Exact-HEAD Chromium gate missing: ' + runner);
  assert.ok(early.includes('@media (prefers-reduced-transparency: reduce)'));
  assert.ok(early.includes('@media (prefers-reduced-motion: reduce)'));
});
