import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = path => readFileSync(resolve(process.cwd(), path), 'utf8');
const retired = read('src/styles/v052-final-audit.css');
const finalCss = read('src/styles/v056-right-workspace-v2.css');

// Same complete selector + at-rule ancestry + property; shorthand or
// specificity-different CSS is deliberately not called a safe retirement.
const cases = [
  [
    "",
    ".nfc-page-header",
    "min-height",
    "0"
  ],
  [
    "",
    ".nfc-page-header",
    "gap",
    "28px"
  ],
  [
    "",
    ".nfc-page-header-copy",
    "min-width",
    "0"
  ],
  [
    "",
    ".nfc-page-header-copy",
    "max-width",
    "min(980px, 74vw)"
  ],
  [
    "",
    ".nfc-page-description",
    "max-width",
    "82ch"
  ],
  [
    "",
    ".nfc-data-panel-header",
    "gap",
    "18px"
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
    "gap",
    "15px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-data-panel-header",
    "align-items",
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
      const selector = css.slice(start, i)
        .replace(/\/\*[\s\S]*?\*\//g, '').trim().replace(/\s+/g, ' ');
      const context = stack.filter(item => item.selector.startsWith('@'))
        .map(item => item.selector).join(' > ');
      stack.push({ selector, context, bodyStart: i + 1 });
      start = i + 1;
    } else if (ch === '}') {
      const block = stack.pop();
      assert.ok(block, 'Balanced CSS blocks required');
      const body = css.slice(block.bodyStart, i);
      if (!block.selector.startsWith('@') && !body.includes('{')) {
        const declarations = new Map();
        for (const entry of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = entry.indexOf(':');
          if (colon !== -1) declarations.set(
            entry.slice(0, colon).trim(), entry.slice(colon + 1).trim());
        }
        rules.push({ selector: block.selector, context: block.context, declarations });
      }
      start = i + 1;
    } else if (ch === ';' && stack.length === 0) start = i + 1;
  }
  assert.equal(stack.length, 0, 'All CSS groups must remain balanced');
  return rules;
}

const early = leafRules(retired), late = leafRules(finalCss);
const match = (rules, context, selector) => rules.filter(x =>
  x.context === context && x.selector === selector);

test('13 v052 shadows stay retired; all final v056 values remain exact', () => {
  assert.equal(cases.length, 13);
  assert.equal(new Set(cases.map(c => c.slice(0, 3).join('|'))).size, 13);
  for (const [context, selector, property, value] of cases) {
    const label = context + '/' + selector + '/' + property;
    assert.ok(match(early, context, selector).every(x =>
      !x.declarations.has(property)), 'Old CSS shadow returned: ' + label);
    const actual = match(late, context, selector)
      .filter(x => x.declarations.has(property));
    assert.ok(actual.length > 0, 'Final v056 owner absent: ' + label);
    assert.equal(actual.at(-1).declarations.get(property), value,
      'Final v056 declaration changed without new browser review: ' + label);
  }
});

test('independent v052 layout/focus/phone declarations remain intact', () => {
  for (const [context, selector, property, value] of [
    ['', '.nfc-page-header', 'margin-bottom', '20px'],
    ['', '.nfc-page-description', 'text-wrap', 'pretty'],
    ['', '.nfc-data-panel-header', 'min-width', '0'],
    ['', '.nfc-login-shell', 'min-height', '100dvh'],
    ['@media (max-width: 767px)', '.nfc-data-panel-header', 'flex-wrap', 'wrap'],
    ['@media (max-width: 767px)', '.nfc-login-panel', 'border-radius', '16px'],
  ]) {
    assert.ok(match(early, context, selector).some(x =>
      x.declarations.get(property) === value),
    'Independent CSS declaration must survive: ' + selector + ' / ' + property);
  }
  assert.ok(retired.includes('.nfc-table-link:focus-visible,'));
  assert.ok(retired.includes('@media (prefers-reduced-motion: reduce)'));
  assert.doesNotMatch(retired, /^[ \t]+$/m, 'No whitespace-only lines introduced');
});

test('v052 precedes v056 and all existing read-only browser regressions stay gated', () => {
  const entry = read('src/main.tsx');
  const earlyImport = entry.indexOf("import './styles/v052-final-audit.css';");
  const lateImport = entry.indexOf("import './styles/v056-right-workspace-v2.css';");
  const nativeImport = entry.indexOf("import './styles/console-v2.css';");
  assert.ok(earlyImport >= 0 && earlyImport < lateImport && lateImport < nativeImport);
  const workflow = read('../.github/workflows/ui-v044-validation.yml');
  for (const name of ['browser-full-route-visual.mjs',
    'browser-workspace-cascade.mjs', 'browser-overlay-smoke.mjs']) {
    assert.ok(workflow.includes(name), 'Readonly Chromium CI runner lost: ' + name);
  }
});
