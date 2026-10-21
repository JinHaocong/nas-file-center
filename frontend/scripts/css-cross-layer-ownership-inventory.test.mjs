import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Historical global layers only, in their real main.tsx import order.
// Native Console v2 page owners are tested separately; including them in this
// inventory would incorrectly label intentional feature overrides as dead CSS.
const layers = [
  'v048.css', 'v048-detail.css', 'v049-workspace.css',
  'v050-layout.css', 'v051-product-polish.css', 'v052-final-audit.css',
  'v054-premium-system.css', 'v055-workspace-breathing.css',
  'v056-right-workspace-v2.css',
];
const read = path => readFileSync(resolve(process.cwd(), path), 'utf8');
const important = value => /!important\s*$/i.test(value);

// Keep exact at-rule ancestry: a mobile declaration does not shadow a
// desktop declaration. This intentionally DOES NOT evaluate specificity,
// shorthands, selector intersection, conditional supports, or runtime paint.
function leafDeclarations(css, file) {
  const output = [];
  const stack = [];
  let segmentStart = 0;
  let comment = false, quote = null, escaped = false;
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
      const selector = css.slice(segmentStart, i)
        .replace(/\/\*[\s\S]*?\*\//g, '').trim().replace(/\s+/g, ' ');
      stack.push({
        selector, from: i + 1,
        context: stack.filter(entry => entry.selector.startsWith('@'))
          .map(entry => entry.selector).join(' > '),
      });
      segmentStart = i + 1;
    } else if (ch === '}') {
      const entry = stack.pop();
      assert.ok(entry, file + ': unmatched closing brace');
      const body = css.slice(entry.from, i);
      if (!entry.selector.startsWith('@') && !body.includes('{')) {
        for (const field of body.replace(/\/\*[\s\S]*?\*\//g, '').split(';')) {
          const colon = field.indexOf(':');
          if (colon < 1) continue;
          const property = field.slice(0, colon).trim();
          const value = field.slice(colon + 1).trim();
          if (property && value) {
            output.push({ file, context: entry.context,
              selector: entry.selector, property, value });
          }
        }
      }
      segmentStart = i + 1;
    } else if (ch === ';' && stack.length === 0) segmentStart = i + 1;
  }
  assert.equal(stack.length, 0, file + ': unclosed CSS block');
  return output;
}

const keyOf = item => [item.context, item.selector, item.property].join(' | ');
function crossFileInventory(sheets) {
  const groups = new Map();
  for (const [file, css] of sheets) {
    for (const record of leafDeclarations(css, file)) {
      const key = keyOf(record);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(record);
    }
  }
  // A repeated property in a single file is NOT a cross-file ownership
  // candidate; multiple files must contribute to the exact same key.
  return [...groups].filter(([, records]) =>
    new Set(records.map(record => record.file)).size > 1);
}

test('historical CSS layers retain stable cascade before native Console owners', () => {
  const entry = read('src/main.tsx');
  const indexes = layers.map(name => {
    const marker = "import './styles/" + name + "';";
    const first = entry.indexOf(marker);
    assert.ok(first >= 0, 'Missing CSS import: ' + name);
    assert.equal(entry.indexOf(marker, first + 1), -1, 'Duplicate CSS import: ' + name);
    return first;
  });
  for (let i = 1; i < indexes.length; i += 1) {
    assert.ok(indexes[i - 1] < indexes[i], 'Changed historical CSS owner order: ' + layers[i]);
  }
  assert.ok(entry.indexOf("import './index.css';") < indexes[0]);
  assert.ok(indexes.at(-1) < entry.indexOf("import './styles/console-v2.css';"));
  assert.ok(read('src/styles/v047.css').startsWith("@import './tokens.css';"));
});

test('cross-layer scanner keeps @media boundaries and single-file duplicates distinct', () => {
  const sample = [
    ['early.css', '@media (max-width: 767px) { .x { color: red !important; } } .x { color: blue; }'],
    ['late.css', '.x { color: green; } @media (max-width: 767px) { .x { color: black; } }'],
  ];
  const groups = crossFileInventory(sample);
  assert.equal(groups.length, 2);
  assert.ok(groups.some(([key, records]) =>
    key.startsWith('@media (max-width: 767px) |') && records.length === 2));
  assert.ok(groups.some(([key, records]) =>
    key.startsWith(' | .x | color') && records.length === 2));
  assert.equal(crossFileInventory([['one.css', '.x { color: red; color: blue; }']]).length, 0);
  assert.equal(important('red !important'), true);
  assert.equal(important('red'), false);
});

test('remaining historical ownership overlaps stay inventoried, not auto-retired', () => {
  const sheets = layers.map(file => [file, read('src/styles/' + file)]);
  const overlaps = crossFileInventory(sheets);
  const changedValues = overlaps.filter(([, records]) =>
    records.some(record => record.value !== records.at(-1).value));
  // This baseline bounds newly introduced overlapping owners. A decrease is
  // allowed, but still requires independent targeted browser/visual review.
  assert.ok(overlaps.length <= 212,
    'New cross-file CSS overlap: update ownership review, not just the baseline');
  assert.ok(changedValues.length <= 161,
    'New differently-valued CSS overlap needs computed-style review');

  // Earlier !important declarations can defeat the last non-important
  // declaration despite the same spelling/context. Do not remove or mark
  // these as proven dead until the actual computed CSS is reviewed.
  const barriers = overlaps.filter(([, records]) => {
    const latest = records.at(-1);
    return !important(latest.value) && records.some(record =>
      record.file !== latest.file && important(record.value));
  });
  const expected = [
    ['', '.nfc-data-panel-header', 'background', 'v048.css', 'v056-right-workspace-v2.css'],
    ['', '.nfc-header.nfc-header', 'border', 'v049-workspace.css', 'v056-right-workspace-v2.css'],
    ['', '.nfc-header.nfc-header', 'background', 'v049-workspace.css', 'v056-right-workspace-v2.css'],
    ['', '.nfc-overlay-section', 'border-radius', 'v049-workspace.css', 'v054-premium-system.css'],
    ['', '.nfc-overlay-section', 'background', 'v049-workspace.css', 'v054-premium-system.css'],
    ['@media (max-width: 767px)', '.nfc-header.nfc-header', 'border',
      'v049-workspace.css', 'v056-right-workspace-v2.css'],
  ];
  assert.deepEqual(barriers.map(([key]) => key).sort(),
    expected.map(row => row.slice(0, 3).join(' | ')).sort(),
    'Importance barriers changed; inspect actual computed winner before altering CSS');
  for (const [context, selector, property, oldFile, lastFile] of expected) {
    const records = barriers.find(([key]) =>
      key === [context, selector, property].join(' | '))?.[1];
    assert.ok(records, 'Missing protected historical importance barrier: ' + selector);
    assert.ok(records.some(record => record.file === oldFile && important(record.value)),
      'Expected earlier important declaration changed: ' + selector + ' ' + property);
    assert.equal(records.at(-1).file, lastFile);
    assert.equal(important(records.at(-1).value), false);
  }

  const workflow = read('../.github/workflows/ui-v044-validation.yml');
  for (const runner of ['browser-full-route-visual.mjs',
    'browser-workspace-cascade.mjs', 'browser-overlay-smoke.mjs']) {
    assert.ok(workflow.includes(runner), 'Readonly Chromium gate lost: ' + runner);
  }
  console.log('[CSS CROSS-LAYER] ' + overlaps.length + ' exact-context cross-file candidates; ' +
    changedValues.length + ' differing-value candidates; ' +
    barriers.length + ' important-precedence barriers. Not dead-code counts.');
});

test('real Chromium matrix pins native header computed winner over legacy importance barriers', () => {
  const browser = read('scripts/browser-workspace-cascade.mjs');
  for (const marker of [
    'async function auditNativeHeaderOwnership(page, item, width, theme)',
    'await auditNativeHeaderOwnership(page, item, width, theme);',
    'native-header-cross-layer-owner-audit.json',
    'WIDTHS.length * THEMES.length * PAGES.length',
    "['0px', '0px', '1px', '0px']",
    "label + ': historical floating shadow returned'",
  ]) {
    assert.ok(browser.includes(marker), 'Actual browser cascade gate is missing: ' + marker);
  }
  const native = read('src/styles/console-v2.css');
  assert.match(native,
    /\.nfc-v2-shell \.nfc-v2-header\.nfc-header\s*\{[^}]*border: 0 !important;[^}]*border-bottom: 1px solid var\(--v2-line\) !important;[^}]*background: var\(--v2-paper\) !important;/,
    'Native shell must keep a higher-specificity important header owner');
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  assert.ok(ci.includes('node scripts/browser-workspace-cascade.mjs'),
    'Computed CSS owner audit must stay inside the exact-HEAD Chromium gate');
});

test('actual DataPanel Chromium paint guards legacy gradient and important background', () => {
  const browser = read('scripts/browser-workspace-cascade.mjs');
  for (const marker of [
    'async function auditNativePanelHeaderOwnership(page, item, width, theme)',
    'await auditNativePanelHeaderOwnership(page, item, width, theme);',
    'native-data-panel-header-cascade-audit.json',
    'WIDTHS.length * THEMES.length * PAGES.length',
    "panel.backgroundImage === 'none'",
    "document.querySelectorAll('.nfc-overlay-section').length",
  ]) {
    assert.ok(browser.includes(marker),
      'Real mounted DataPanel style/audit coverage lost: ' + marker);
  }
  const native = read('src/styles/v056-right-workspace-v2.css');
  assert.match(native,
    /\.nfc-app-main \.nfc-data-panel > \.nfc-data-panel-header,[\s\S]*?border-bottom: 1px solid var\(--nfc-shell-card-border\) !important;[\s\S]*?background: transparent !important;/,
    'The late native DataPanel must retain its own bottom separator and transparent background');
  const old = read('src/styles/v048.css');
  assert.match(old, /\.nfc-data-panel-header\s*\{[^}]*background: transparent !important;/,
    'Historical global declaration inventory changed; rerun owner review');
  const ci = read('../.github/workflows/ui-v044-validation.yml');
  assert.ok(ci.includes('node scripts/browser-workspace-cascade.mjs'));
});
