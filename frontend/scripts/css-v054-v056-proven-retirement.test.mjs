import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = path => readFileSync(resolve(process.cwd(), path), 'utf8');
const earlySource = read('src/styles/v054-premium-system.css');
const finalSource = read('src/styles/v056-right-workspace-v2.css');
const cases = [
  [
    "@media (max-width: 1199px)",
    ".nfc-app-main .nfc-page-header",
    "min-height",
    "0"
  ],
  [
    "@media (max-width: 1199px)",
    ".nfc-app-main .nfc-page-header-copy",
    "max-width",
    "100%"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "min-height",
    "0"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "padding",
    "0 0 18px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "gap",
    "15px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-title",
    "font-size",
    "24px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-description",
    "font-size",
    "12.75px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-description",
    "line-height",
    "1.6"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-data-panel-header",
    "padding",
    "13px 14px 11px"
  ],
  [
    "@media (max-width: 420px)",
    ".nfc-app-main .nfc-page-title",
    "font-size",
    "22px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "min-height",
    "52px"
  ]
];

// Parse exact complete selectors and preserve nested at-rule ancestry.
// No shorthand/specificity equivalence is inferred from a text match.
function leafRules(css) {
  const rules = [], stack = [];
  let start = 0, quote = null, comment = false, escaped = false;
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
      const context = stack.filter(x => x.selector.startsWith('@'))
        .map(x => x.selector).join(' > ');
      stack.push({ selector, context, from: i + 1 });
      start = i + 1;
    } else if (ch === '}') {
      const block = stack.pop();
      assert.ok(block, 'CSS closing braces must remain balanced');
      const body = css.slice(block.from, i);
      if (!block.selector.startsWith('@') && !body.includes('{')) {
        const declarations = new Map();
        for (const item of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = item.indexOf(':');
          if (colon > 0) declarations.set(item.slice(0, colon).trim(),
            item.slice(colon + 1).trim());
        }
        rules.push({ selector: block.selector, context: block.context, declarations });
      }
      start = i + 1;
    } else if (ch === ';' && stack.length === 0) start = i + 1;
  }
  assert.equal(stack.length, 0, 'All CSS media blocks must remain balanced');
  return rules;
}

const early = leafRules(earlySource), final = leafRules(finalSource);
const rules = (collection, media, selector) => collection.filter(
  item => item.context === media && item.selector === selector);

test('11 exact-context v054 shadows stay retired and their v056 winners stay fixed', () => {
  assert.equal(cases.length, 11);
  assert.equal(new Set(cases.map(x => x.slice(0, 3).join('|'))).size, 11);
  for (const [media, selector, property, value] of cases) {
    const name = media + ' | ' + selector + ' | ' + property;
    assert.ok(rules(early, media, selector).every(x =>
      !x.declarations.has(property)), 'Retired v054 property returned: ' + name);
    const owners = rules(final, media, selector)
      .filter(x => x.declarations.has(property));
    assert.ok(owners.length, 'Later v056 property owner vanished: ' + name);
    assert.equal(owners.at(-1).declarations.get(property), value,
      'Later authoritative value changed without browser review: ' + name);
  }
});

test('mobile layout, command controls, and accessibility-independent declarations survive', () => {
  for (const [media, selector, property, value] of [
    ['@media (max-width: 1199px)', '.nfc-app-main .nfc-page-header', 'gap', '18px'],
    ['@media (max-width: 767px)', '.nfc-app-main .nfc-page-content', 'padding-top', '16px'],
    ['@media (max-width: 767px)', '.nfc-app-main .nfc-page-header::after', 'width', '52px'],
    ['@media (max-width: 767px)', '.nfc-app-main .nfc-data-panel-header', 'min-height', '58px'],
    ['@media (max-width: 767px)', '.nfc-app-main .nfc-page-actions .nfc-action-bar',
      'justify-content', 'flex-start'],
    ['@media (max-width: 420px)', '.nfc-app-main .nfc-metric-card', 'min-height', '102px'],
  ]) assert.ok(rules(early, media, selector).some(x =>
    x.declarations.get(property) === value),
  'Unrelated retained v054 property disappeared: ' + media + ' ' + selector + ' ' + property);
  for (const marker of [
    '.nfc-app-main .nfc-row-actions:focus-within',
    '@media (prefers-reduced-motion: reduce)',
    '@media (prefers-reduced-transparency: reduce)',
  ]) assert.ok(earlySource.includes(marker), 'Accessibility rule lost: ' + marker);
  assert.ok(earlySource.length > 30000, 'Legacy native visual source was truncated');
  assert.doesNotMatch(earlySource, /^[ \t]+$/m,
    'Do not introduce whitespace-only lines during source retirement');
});

test('import precedence and existing read-only Chromium gate remain unchanged', () => {
  const main = read('src/main.tsx');
  const old = main.indexOf("import './styles/v054-premium-system.css';");
  const late = main.indexOf("import './styles/v056-right-workspace-v2.css';");
  const native = main.indexOf("import './styles/console-v2.css';");
  assert.ok(old >= 0 && old < late && late < native);
  const workflow = read('../.github/workflows/ui-v044-validation.yml');
  for (const runner of ['browser-full-route-visual.mjs',
    'browser-workspace-cascade.mjs', 'browser-overlay-smoke.mjs'])
    assert.ok(workflow.includes(runner),
      'Exact-HEAD readonly Chromium regression missing: ' + runner);
});
