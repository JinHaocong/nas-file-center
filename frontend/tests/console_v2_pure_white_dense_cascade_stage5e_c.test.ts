import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const v049 = read('src/styles/v049-workspace.css');
const v056 = read('src/styles/v056-right-workspace-v2.css');
const browser = read('scripts/browser-workspace-cascade.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

function rules(selector: string): string[] {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  const expression = new RegExp('(?:^|\\n)\\s*' + escaped + '\\s*\\{([^}]*)\\}', 'g');
  return [...v049.matchAll(expression)].map(match => match[1]);
}

describe('Pure White Stage 5E-C v049 historical shadows and dense ledger acceptance', () => {
  test('24 early desktop properties no longer shadow their later same-selector winners', () => {
    const retired: Array<[string, string[]]> = [
      ['.nfc-header.nfc-header', ['margin', 'border', 'box-shadow', 'backdrop-filter', '-webkit-backdrop-filter']],
      ['.nfc-page-header', ['min-height', 'margin', 'padding', 'align-items', 'gap', 'border', 'border-radius', 'box-shadow']],
      ['.nfc-page-header-copy', ['max-width']],
    ];
    let total = 0;
    for (const [selector, properties] of retired) {
      const blocks = rules(selector);
      assert.ok(blocks.length >= 2, selector + ' lost late authoritative block');
      const first = blocks[0];
      const later = blocks.slice(1).join('\n');
      for (const property of properties) {
        const pattern = new RegExp('(?:^|\\n)\\s*' + property + '\\s*:', 'm');
        assert.doesNotMatch(first, pattern, selector + ' early shadow ' + property);
        assert.match(later, pattern, selector + ' missing late winner ' + property);
        total++;
      }
    }
    // Both later v049 metric-card geometry shadows now belong to v056.
    // Keep the original two assertions in the 24-property acceptance total.
    const metricHistorical = [...v049.matchAll(/^\.nfc-metric-card\s*\{([^}]*)\}/gm)];
    assert.equal(metricHistorical.length, 2);
    const metricCanonical = v056.match(/^\.nfc-metric-card\s*\{([^}]*)\}/m)?.[1];
    assert.ok(metricCanonical, 'Missing exact-selector v056 metric-card owner');
    for (const [property, value] of [['min-height', '104px'], ['padding', '16px 17px']]) {
      const pattern = new RegExp('(?:^|\\n)\\s*' + property + '\\s*:');
      assert.ok(metricHistorical.every(match => !pattern.test(match[1])),
        'Obsolete v049 metric geometry reintroduced: ' + property);
      assert.ok(metricCanonical.includes(property + ': ' + value + ';'),
        'Exact v056 metric geometry drift: ' + property);
      total += 1;
    }

    // This panel selector now has ONE unconditional v049 block (the
    // independently meaningful later min-height/padding/background owner).
    // The obsolete earlier min-height shadow must stay absent; the v056
    // exact-selector owner still explicitly resets the desktop min-height.
    const panelRoot = [...v049.matchAll(/^\.nfc-data-panel-header\s*\{([^}]*)\}/gm)];
    assert.equal(panelRoot.length, 1,
      'Old unconditional v049 panel-header shadow must not be reintroduced');
    assert.match(panelRoot[0][1], /min-height:\s*62px;/);
    assert.match(panelRoot[0][1], /padding:\s*15px 18px 14px;/);
    const panelCanonical = v056.match(/^\.nfc-data-panel-header\s*\{([^}]*)\}/m)?.[1];
    assert.ok(panelCanonical, 'Canonical v056 panel-header owner must survive');
    assert.match(panelCanonical, /min-height:\s*0;/);
    assert.match(panelCanonical, /gap:\s*18px;/);
    total += 1;

    // The old action-row padding is now its sole unconditional v049 rule.
    const actionBlocks = rules('.nfc-page-actions');
    assert.equal(actionBlocks.length, 1, 'Retain only the independent v049 action padding');
    assert.match(actionBlocks[0], /padding-bottom:\s*0;/);
    assert.doesNotMatch(actionBlocks[0], /(?:^|\n)\s*(?:align-self|gap)\s*:/);
    total += 1;

    // The six desktop metric-grid properties graduated from late v049 to
    // later-imported v056: source-level leaf ownership is pinned separately
    // by css-historical-cascade-convergence.test.mjs.
    assert.doesNotMatch(v049, /^\.nfc-metric-grid\s*\{/m,
      'Historical unconditional metric-grid declarations must stay retired');
    const metricBase = v056.match(/(?:^|\n)\.nfc-metric-grid\s*\{([^}]*)\}/)?.[1];
    assert.ok(metricBase, 'v056 unconditional metric-grid owner is required');
    for (const property of ['gap', 'overflow', 'border', 'border-radius', 'background', 'box-shadow']) {
      const rule = new RegExp('(?:^|\\n)\\s*' + property + '\\s*:');
      assert.match(metricBase, rule, 'v056 final metric property ' + property);
      total += 1;
    }

    assert.equal(total, 24);
    assert.ok(rules('.nfc-header.nfc-header')[0].includes('position: sticky'));
    assert.ok(rules('.nfc-page-header')[0].includes('border-bottom: 1px'));
    assert.ok(rules('.nfc-metric-grid').some(block => block.includes('grid-template-columns')),
      'Independent responsive metric columns must survive');
    assert.ok(read('src/main.tsx').includes("import './styles/v049-workspace.css';"));
  });

  test('dense fixture exercises real Plans/Tasks/Indexes tables and mobile cards', () => {
    for (const needle of [
      'const DENSE_ROOT =', 'const DENSE_PAGES =',
      "path: '/plans', id: 'plans'", "path: '/tasks', id: 'tasks'",
      "path: '/indexes', id: 'indexes'",
      '.nfc-plan-mobile-card', '.nfc-task-mobile-card', '.nfc-index-mobile-card',
      '.nfc-v2-plan-table tbody tr', '.nfc-v2-task-table tbody tr',
      '.nfc-v2-indexes-table tbody tr',
      'VALIDATION_PATH_IDENTITY_CHANGED', 'Unavailable-Recovery-Snapshot',
      'const expectedCount = item.count ?? 2', 'Mobile dense card exceeds viewport bounds',
      'Wide-table scrollport exceeds viewport', 'Wide table must own horizontal overflow',
      'getComputedStyle(scroll).overflowX',
      'const isMobile = width < 768',
      'await inspectDense(page, item, width)',
      "path: resolve(OUT, item.id + '-dense-' + label + '.png')",
    ]) assert.ok(browser.includes(needle), needle);
  });

  test('all synthetic data must remain read-only, off-origin blocked, and prior six pages preserved', () => {
    for (const needle of [
      "request.method() !== 'GET'", 'url.origin !== BASE',
      'status: 405', 'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []', "let denseMode = false",
      'denseMode = true', 'denseMode = false',
      'JSON.stringify(fixture(url.pathname, denseMode))',
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
      '32/32 cases, 352 screenshots',
      "'/dashboard'", "'/media'", "'/quarantine'",
    ]) assert.ok(browser.includes(needle), needle);
    assert.doesNotMatch(browser, /(?:plansApi|tasksApi|indexesApi)\.(?:execute|delete|purge|freeze|validate)\(/);
    for (const needle of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'frontend/artifacts/browser-workspace-cascade/*.png',
    ]) assert.ok(workflow.includes(needle), needle);
  });
});
