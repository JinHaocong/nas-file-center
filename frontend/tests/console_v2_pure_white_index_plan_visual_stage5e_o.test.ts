import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Pure White Stage 5E-O actual screenshot regression safety', () => {
  test('Index root dialog uses base layer so its nested directory picker stays in front', () => {
    const indexes = read('src/pages/Indexes/index.tsx');
    const css = read('src/styles/console-v2-indexes.css');
    const pickerCss = read('src/styles/console-v2-directory-modal.css');
    const confirmationCss = read('src/styles/console-v2-task-overlays.css');
    const generic = read('src/styles/console-v2.css');
    assert.match(indexes, /<Dialog.Overlay className="nfc-v2-dialog-overlay" \/>/);
    assert.doesNotMatch(indexes, /<Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" \/>/);
    assert.doesNotMatch(css, /\.nfc-v2-index-create-dialog\[data-state='open'\]\s*\{\s*z-index:\s*1301/);
    assert.match(generic, /\.nfc-v2-dialog-overlay\s*\{[\s\S]*?z-index:\s*1100/);
    assert.match(generic, /\.nfc-v2-dialog\[data-state='open'\]\s*\{[\s\S]*?z-index:\s*1101/);
    assert.match(pickerCss, /z-index: 1201/);
    assert.match(pickerCss, /\.nfc-v2-directory-overlay \{ z-index: 1200; \}/);
    assert.match(confirmationCss, /\.nfc-v2-confirm-overlay \{ z-index: 1300 !important; \}/);
    assert.match(confirmationCss, /\.nfc-v2-confirm-dialog\.nfc-v2-dialog\[data-state='open'\] \{ z-index: 1301 !important;/);
    assert.match(indexes, /<DirectoryPicker multiple=\{false\} allowManualInput=\{true\}/);
    assert.match(indexes, /indexesApi.createIndex\(root\)/);
    assert.match(indexes, /root.startsWith\('\/'\)/);
  });

  test('Plans list and PlanItem detail table columns have distinct CSS ownership', () => {
    const detail = read('src/styles/console-v2-plan-detail.css');
    const list = read('src/styles/console-v2-phase2.css');
    const listPage = read('src/pages/Plans/index.tsx');
    for (const line of detail.split('\n').filter(x => x.includes('.nfc-v2-plan-table'))) {
      assert.match(line, /\.nfc-plan-detail-page \.nfc-v2-plan-table/,
        'Every PlanDetail table rule must be page-scoped');
    }
    assert.match(detail, /\.nfc-plan-detail-page \.nfc-v2-plan-table th:nth-child\(1\) \{ width:70px; \}/);
    assert.match(list, /\.nfc-v2-plans-page \.nfc-v2-plan-table \{ min-width: 1160px; table-layout: fixed; \}/);
    assert.match(list, /\.nfc-v2-plans-page \.nfc-v2-plan-table th:nth-child\(1\) \{ width: 29%; \}/);
    assert.match(list, /\.nfc-v2-plans-page \.nfc-v2-plan-name span \{ min-width: 0; overflow-wrap: anywhere;/);
    assert.match(listPage, /<span>\{plan.name\}<\/span>/);
    assert.match(listPage, /<PlanDeleteButton plan=\{plan\}/);
  });

  test('Full existing Chromium matrices assert nested picker and long plan names', () => {
    const indexRunner = read('scripts/browser-indexes-ledger-states.mjs');
    const cascade = read('scripts/browser-workspace-cascade.mjs');
    const ci = read('../.github/workflows/ui-v044-validation.yml');
    for (const token of [
      "create.getByRole('button', { name: '选择目录', exact: true }).click()",
      "assert.deepEqual(nested.z, [1100, 1101, 1200, 1201]",
      'Nested picker must receive pointer hits',
      'Nested picker must fit the viewport',
      'Escape must close picker, not its parent',
      "request.method() !== 'GET'", "assert.deepEqual(writes, []",
      '32/32 cases, 160 screenshots',
    ]) assert.ok(indexRunner.includes(token), token);
    for (const token of [
      "item.id === 'plans' && !isMobile",
      'colWidth < 240 || titleWidth < 140',
      'Plan list name column collapsed',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(cascade.includes(token), token);
    for (const command of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'Upload visual evidence',
    ]) assert.ok(ci.includes(command), command);
  });
});
