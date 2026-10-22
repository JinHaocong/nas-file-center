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
  test('exact v056 desktop owner and independent v049 mobile geometry stay guarded', () => {
    const cases: Array<[string, string, string]> = [
      ['.nfc-header.nfc-header','margin','12px 12px 0'],
      ['.nfc-page-header','padding','0 0 24px'],
      ['.nfc-page-header-copy','max-width','min(980px, 74vw)'],
      ['.nfc-metric-card','min-height','104px'],
      ['.nfc-metric-card','padding','16px 17px'],
      ['.nfc-data-panel-header','min-height','0'],
      ['.nfc-page-actions','padding-bottom','1px'],
      ['.nfc-metric-grid','gap','12px'],
    ];
    for(const [sel,prop,value] of cases) {
      assert.ok(rules(sel).every(body=>!body.includes(prop+':')),
        'Old v049 exact desktop property returned: '+sel+' '+prop);
      const re=new RegExp('(?:^|\\n)'+sel.replace(/\./g,'\\.')+'\\s*\\{([^}]*)\\}','g');
      const bodies=[...v056.matchAll(re)].map(match=>match[1]);
      assert.ok(bodies.some(body=>body.includes(prop+': '+value+';')),
        'Final v056 CSS declaration changed: '+sel+' '+prop);
    }
    assert.match(v049,/\.nfc-header\.nfc-header\s*\{[^}]*border:\s*1px solid var\(--nfc-border-soft\) !important;/);
    assert.match(v049,/@media \(max-width: 767px\)[\s\S]*\.nfc-metric-grid\s*\{[^}]*grid-template-columns:/);
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
