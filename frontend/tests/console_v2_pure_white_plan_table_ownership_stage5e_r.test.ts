import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Pure White Stage 5E-R: Plans list vs PlanItem detail CSS ownership', () => {
  test('every shared plan table structural selector in Phase2 belongs only to the list page', () => {
    const css = read('src/styles/console-v2-phase2.css');
    const scopedSelectors = css.split('\n').filter(line =>
      line.trimStart().startsWith('.') && line.includes('.nfc-v2-plan-table'));
    assert.ok(scopedSelectors.length >= 6, 'list table has at least six structural and sizing rules');
    for (const selector of scopedSelectors) {
      assert.match(selector, /\.nfc-v2-plans-page \.nfc-v2-plan-table/,
        'Unscoped plan-table rule could change PlanDetail ledger: ' + selector);
    }
    assert.match(css, /\.nfc-v2-plans-page \.nfc-v2-plan-table-scroll \{ width: 100%; max-width: 100%; overflow-x: auto; \}/);
    assert.match(css, /\.nfc-v2-shell \.nfc-v2-plans-page \.nfc-v2-plan-table \{[\s\S]*?min-width: 860px;/);
    assert.match(css, /\.nfc-v2-plans-page \.nfc-v2-plan-table th \{ padding: 13px 17px;/);
    assert.match(css, /\.nfc-v2-plans-page \.nfc-v2-plan-table td \{ padding: 15px 17px;/);
    assert.match(css, /\.nfc-v2-plans-page \.nfc-v2-plan-table tbody tr:hover \{/);
    assert.match(css, /\.nfc-v2-plans-page \.nfc-v2-plan-table \{ min-width: 1160px; table-layout: fixed; \}/);
    assert.match(css, /\.nfc-v2-plans-page \.nfc-v2-plan-table th:nth-child\(1\) \{ width: 29%; \}/);
  });

  test('PlanDetail still exclusively owns its ledger row padding, hover, focus and ID columns', () => {
    const detail = read('src/styles/console-v2-plan-detail.css');
    for (const line of detail.split('\n').filter(x => x.includes('.nfc-v2-plan-table'))) {
      assert.match(line, /\.nfc-plan-detail-page \.nfc-v2-plan-table/,
        'Detail ledger rule must remain page-owned: ' + line);
    }
    assert.match(detail, /\.nfc-plan-detail-page \.nfc-v2-plan-table th \{ padding:11px 10px;/);
    assert.match(detail, /\.nfc-plan-detail-page \.nfc-v2-plan-table td \{ padding:12px 10px;/);
    assert.match(detail, /\.nfc-plan-detail-page \.nfc-v2-plan-table tbody tr:focus-within/);
    assert.match(detail, /\.nfc-plan-detail-page \.nfc-v2-plan-table th:nth-child\(1\) \{ width:70px; \}/);
    assert.match(detail, /\.nfc-plan-detail-page \.nfc-v2-plan-table-scroll \{ max-width:100%;overflow-x:auto;/);
  });

  test('CSS import order and existing read-only visual gates remain', () => {
    const main = read('src/main.tsx');
    const scripts = read('../.github/workflows/ui-v044-validation.yml');
    const list = read('src/pages/Plans/index.tsx');
    const detail = read('src/pages/Plans/PlanDetail.tsx');
    assert.ok(main.indexOf("import './styles/console-v2-phase2.css';") <
      main.indexOf("import './styles/console-v2-plan-detail.css';"));
    assert.match(list, /<table className="nfc-v2-plan-table">/);
    assert.match(detail, /nfc-plan-detail-page/);
    for (const run of ['browser-plan-lifecycle.mjs', 'browser-workspace-cascade.mjs']) {
      assert.ok(scripts.includes('node scripts/' + run), run);
    }
    assert.match(read('scripts/browser-workspace-cascade.mjs'),
      /Plan list name column collapsed/);
  });
});
