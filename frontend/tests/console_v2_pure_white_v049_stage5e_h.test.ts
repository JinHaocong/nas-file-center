import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const v049 = read('src/styles/v049-workspace.css');
const v056 = read('src/styles/v056-right-workspace-v2.css');
const workspace = read('scripts/browser-workspace-cascade.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');
const entry = read('src/main.tsx');

function blocks(selector: string): string[] {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  const pattern = new RegExp('(?:^|\\n)' + escaped + '\\s*\\{([^}]*)\\}', 'g');
  return [...v049.matchAll(pattern)].map(match => match[1]);
}
function property(block: string, name: string): string | undefined {
  const escaped = name.replace(/-/g, '\\-');
  const match = block.match(new RegExp('(?:^|\\n)\\s*' + escaped + ':([^;]*);'));
  return match?.[1].trim();
}

// Only unconditional early same-selector properties with later winners of equal
// importance were retired. Responsive @media rules and shared styles are intact.
const retired: Array<[string, string[], number]> = [
  ['.nfc-header.nfc-header', ['top', 'min-height', 'padding', 'border-radius'], 2],
  ['.nfc-header-status', ['background'], 2],
  ['.nfc-page-header', ['background'], 2],
  ['.nfc-data-panel-header', ['padding', 'border-bottom-color'], 1],
  ['.nfc-metric-card', ['border'], 2],
  ['.nfc-metric-card:last-child', ['border-right'], 1],
  ['.nfc-metric-card:hover', [], 1],
  ['.nfc-metric-value', ['margin-top'], 1],
  ['.nfc-system-controls-page .nfc-settings-grid', ['gap'], 1],
  ['.nfc-system-controls-page .nfc-settings-grid > .nfc-data-panel > .nfc-data-panel-header',
    ['min-height', 'padding'], 2],
  ['.nfc-system-controls-page .nfc-settings-grid > .nfc-data-panel > .nfc-data-panel-body',
    ['padding'], 1],
  ['.nfc-system-controls-page .nfc-settings-subpanel', ['border-radius'], 2],
  ['.nfc-directory-browser-row', ['min-height', 'padding'], 1],
];

describe('Pure White Stage 5E-H v049 late-authority convergence', () => {
  test('23 shadowed early declarations are gone but their exact-selector winners remain', () => {
    let count = 0;
    for (const [selector, removed, expectedDesktopRules] of retired) {
      const rules = blocks(selector);
      assert.ok(rules.length >= expectedDesktopRules, selector + ' missing late winner');
      // Some selectors also have a separate later @media mobile version.
      if (expectedDesktopRules === 1) {
        // A formerly declaration-only first selector block has been removed.
        assert.equal(rules.length, 1, selector + ' must have only final authority');
      } else {
        assert.ok(rules.length >= 2, selector + ' must preserve retained early props');
      }
      const winning = rules[expectedDesktopRules - 1];
      if (selector === '.nfc-data-panel-header') {
        assert.equal(property(winning, 'gap'), undefined,
          'Old v049 panel-header gap must remain retired');
        const late = read('src/styles/v056-right-workspace-v2.css');
        assert.match(late, /\.nfc-data-panel-header\s*\{[^}]*gap:\s*18px;/,
          'Later v056 exact-selector gap owner must survive');
      }
      for (const name of removed) {
        if (expectedDesktopRules === 2) {
          assert.equal(property(rules[0], name), undefined,
            selector + ' still has early shadow ' + name);
        }
        assert.notEqual(property(winning, name), undefined,
          selector + ' missing late declaration ' + name);
        count++;
      }
    }
    // Five Stage 5E-H assertions now follow the exact later-imported
    // same-selector v056 owner instead of obsolete late v049 properties.
    const canonicalMetric = v056.match(/^\.nfc-metric-card\s*\{([^}]*)\}/m)?.[1];
    const canonicalHover = v056.match(/^\.nfc-metric-card:hover\s*\{([^}]*)\}/m)?.[1];
    assert.ok(canonicalMetric && canonicalHover, 'Metric/card hover v056 authority must remain');
    for (const [prop, expected] of [
      ['border-radius', 'var(--nfc-w2-radius-md)'],
      ['background', 'color-mix(in srgb, var(--nfc-w2-surface) 88%, var(--nfc-w2-surface-soft))'],
      ['box-shadow', 'none'],
    ]) {
      assert.equal(property(blocks('.nfc-metric-card')[1], prop), undefined,
        'Retired v049 metric property returned: ' + prop);
      assert.equal(property(canonicalMetric, prop), expected);
      count++;
    }
    for (const [prop, expected] of [['transform', 'none'], ['background', 'var(--nfc-w2-surface)']]) {
      assert.equal(property(blocks('.nfc-metric-card:hover')[0], prop), undefined,
        'Retired v049 hover property returned: ' + prop);
      assert.equal(property(canonicalHover, prop), expected);
      count++;
    }
    assert.equal(count, 23);
  });

  test('retain meaningful base properties, important parity, and final geometry', () => {
    assert.match(blocks('.nfc-header.nfc-header')[0], /position:\s*sticky/);
    assert.match(blocks('.nfc-header.nfc-header')[0], /z-index:\s*30/);
    assert.equal(property(blocks('.nfc-header.nfc-header')[1], 'top'), '12px');
    assert.equal(property(blocks('.nfc-metric-card')[0], 'border-right'),
      '1px solid var(--nfc-v49-line)');
    assert.equal(property(blocks('.nfc-metric-card')[1], 'border'),
      '1px solid var(--nfc-border-soft)');
    assert.ok(property(blocks('.nfc-metric-card')[1], 'transition')?.includes('box-shadow 150ms ease'));
    assert.ok(property(blocks('.nfc-metric-card:hover')[0], 'box-shadow')?.includes('0 14px 34px'));
    assert.equal(property(blocks('.nfc-metric-value')[0], 'margin-top'), '12px');
    assert.equal(property(blocks('.nfc-system-controls-page .nfc-settings-subpanel')[0],
      'border-bottom'), '1px solid var(--nfc-v49-line) !important');
    assert.equal(property(blocks('.nfc-system-controls-page .nfc-settings-subpanel')[1],
      'border-radius'), 'var(--nfc-ui-inner-radius) !important');
    assert.equal(property(blocks('.nfc-directory-browser-row')[0], 'min-height'), '48px');
    assert.match(v049, /@media \(max-width:\s*767px\)/);
    assert.match(v049, /@media \(prefers-reduced-transparency:\s*reduce\)/);
    assert.ok(entry.indexOf("import './styles/v049-workspace.css'") <
      entry.indexOf("import './styles/console-v2.css'"));
  });

  test('all existing read-only Chromium workspace cases and screenshot evidence remain in CI', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      'real six-page empty + five-page dense CSS/status gates',
      "request.method() !== 'GET'", 'url.origin !== BASE',
      'status: 405', 'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(workspace.includes(token), token);
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'frontend/artifacts/browser-workspace-cascade/*.png',
      'frontend/artifacts/browser-media-ledger-states/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
