import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const v049 = read('src/styles/v049-workspace.css');
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
      ['.nfc-page-actions', ['padding-bottom']],
      ['.nfc-data-panel-header', ['min-height']],
      ['.nfc-metric-grid', ['gap', 'overflow', 'border', 'border-radius', 'background', 'box-shadow']],
      ['.nfc-metric-card', ['min-height', 'padding']],
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
    assert.equal(total, 24);
    assert.ok(rules('.nfc-header.nfc-header')[0].includes('position: sticky'));
    assert.ok(rules('.nfc-page-header')[0].includes('border-bottom: 1px'));
    assert.ok(rules('.nfc-metric-grid')[0].includes('grid-template-columns') === false ||
      rules('.nfc-metric-grid')[0].includes('box-shadow') === false);
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
      'Expected two dense records', 'Mobile dense card exceeds viewport bounds',
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
