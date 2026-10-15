import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const css = read('src/styles/v056-right-workspace-v2.css');
const browser = read('scripts/browser-workspace-cascade.mjs');
const entry = read('src/main.tsx');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

function blocks(selector: string): string[] {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  const regex = new RegExp('(?:^|\\n)\\s*' + escaped + '\\s*\\{([^}]*)\\}', 'g');
  return [...css.matchAll(regex)].map(x => x[1]);
}

describe('Pure White Stage 5E-A computed CSS cascade cleanup', () => {
  test('dashboard late specificity remains authoritative with no shadowed desktop spacing', () => {
    const deck = blocks('.nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck');
    const grid = blocks('.nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck .nfc-metric-grid');
    const metric = blocks('.nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck .nfc-metric-card');
    const snap = blocks('.nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck .nfc-snapshot-note');
    const layout = blocks('.nfc-app-main .nfc-dashboard-page .nfc-dashboard-layout');
    const column = blocks('.nfc-app-main .nfc-dashboard-page .nfc-dashboard-main-column');
    assert.match(deck[0], /\bmargin:\s*0;/);
    assert.match(deck[0], /\bgap:\s*10px;/);
    assert.match(grid[0], /\bborder:\s*0;/);
    assert.doesNotMatch(grid[0], /\bgap:/);
    assert.match(metric[0], /\bborder:\s*1px/);
    assert.doesNotMatch(metric[0], /min-height:|padding:/);
    assert.match(snap[0], /border-radius:/);
    assert.doesNotMatch(snap[0], /\bpadding:/);
    assert.match(layout[0], /margin-top:\s*0;/);
    assert.match(layout[0], /\bgap:\s*18px;/);
    assert.match(column[0], /\bgap:\s*18px;/);
    assert.doesNotMatch(layout.join('\n'), /gap:\s*(30|24)px/);
    assert.doesNotMatch(column.join('\n'), /gap:\s*(26|22)px/);
    assert.doesNotMatch(css, /\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-main-column > \.nfc-data-panel\s*\{\s*min-height:\s*240px;/);
  });

  test('Ledger heading and operational spacing retain their final cascade identity', () => {
    const ledger = blocks('.nfc-app-main .nfc-page-layout-ledger > .nfc-page-header');
    assert.equal(ledger.length, 2, 'Desktop and mobile authoritative rules only');
    for (const rule of ledger) assert.match(rule, /margin-bottom:\s*0\s*!important;/);
    assert.doesNotMatch(css, /\.nfc-app-main \.nfc-page-layout-ledger > \.nfc-page-header\s*\{\s*margin-bottom:\s*26px;/);
    const q = blocks('.nfc-app-main .nfc-quarantine-command-center');
    assert.equal(q.length, 2);
    assert.doesNotMatch(q[0], /\bgap:/);
    assert.match(q[1], /gap:\s*0;/);
    const alerts = blocks('.nfc-app-main .nfc-quarantine-page .nfc-page-alert');
    assert.equal(alerts.length, 1);
    assert.match(alerts[0], /margin-bottom:\s*22px/);
    const tasks = blocks('.nfc-app-main .nfc-tasks-page .nfc-worker-status-strip');
    assert.equal(tasks.length, 1);
    assert.match(tasks[0], /margin-bottom:\s*28px/);
    assert.match(blocks('.nfc-app-main .nfc-plan-detail-page .nfc-plan-action-surface')[0],
      /margin-bottom:\s*24px/);
    assert.match(blocks('.nfc-app-main .nfc-advanced-dedupe-page .nfc-dedupe-cockpit')[0],
      /gap:\s*28px/);
  });

  test('native imports and safety components remain untouched and overlay contracts continue', () => {
    assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
      entry.indexOf("import './styles/console-v2.css';"));
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
    assert.ok(css.includes('@media (max-width: 767px)'));
    assert.ok(css.includes('@media (min-width: 768px)'));
    assert.ok(read('src/styles/console-v2.css').includes('.nfc-v2-dialog-overlay'));
    assert.ok(read('src/pages/Plans/PlanDetail.tsx').includes('plansApi.validatePlan(planId)'));
  });

  test('actual Chromium audits Dashboard, Plans, Tasks at 8 widths x 4 effective themes', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      'const THEMES = visualThemes',
      "'/dashboard'", "'/plans'", "'/tasks'",
      "getComputedStyle(head).marginBottom",
      "getComputedStyle(pageContent).overflowY",
      'Metric layout lost grid',
      'Ledger page gap must own vertical rhythm',
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(browser.includes(token), token);
    const shared = read('scripts/visual-fixtures.mjs');
    for (const token of ["mode: 'light'", "mode: 'dark'", "mode: 'system'"]) {
      assert.ok(shared.includes(token), 'Shared real browser matrix missing ' + token);
    }
    assert.ok(browser.includes("from './visual-fixtures.mjs'"));
  });

  test('CI captures seventh browser matrix and all requests remain local GET only', () => {
    for (const token of [
      "request.method() !== 'GET'",
      'url.origin !== BASE',
      'status: 405',
      'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
    ]) assert.ok(browser.includes(token), token);
    for (const token of [
      'Checkout exact candidate HEAD',
      'Verify candidate identity',
      'node scripts/browser-organizer-dedupe-overlays.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'frontend/artifacts/browser-workspace-cascade/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
