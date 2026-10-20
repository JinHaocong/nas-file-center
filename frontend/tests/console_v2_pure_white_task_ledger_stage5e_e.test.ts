import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const browser = read('scripts/browser-task-ledger-states.mjs');
const taskPage = read('src/pages/Tasks/index.tsx');
const taskApi = read('src/api/tasks.ts');
const taskDrawer = read('src/components/tasks/TaskDetailDrawer.tsx');
const ci = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5E-E Tasks complex states', () => {
  test('the 8-width by 4-theme matrix covers long error, page 2, compound filters and recovery', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "'long-error-' + label", "'page-two-' + label",
      "'filtered-empty-' + label", "'list-error-' + label",
      "'ExtremelyLongFilenameWithoutNaturalBreaks'.repeat(18)",
      'assert.equal(await page.locator(row).count(), 50',
      'assert.equal(await page.locator(row).count(), 1',
      "getByRole('button', { name: '下一页' })",
      "selectOption('failed')", "selectOption('media-analysis')",
      "selectOption('running')", "name: '重试', exact: true",
      "params.get('job_type') === 'media-analysis'",
      "params.get('page') === '1'", "params.get('status') === 'failed'",
      'Task inspector exceeds viewport', 'Long error exceeds viewport',
      'Filter bar overflow', 'Pagination horizontal overflow',
      'List error alert overflows', 'Mobile task card overflows viewport',
      'Sheet overlay z-index', 'Sheet content z-index',
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
      '32/32 cases, 160 screenshots',
    ]) assert.ok(browser.includes(token), token);
    assert.match(taskPage, /setPage\(1\)/);
    assert.match(taskPage, /isError\s*\?\s*\(/);
    assert.match(taskPage, /<TaskDetailDrawer/);
    assert.match(taskApi, /searchParams\.set\('page_size'/);
    assert.match(taskApi, /searchParams\.set\('status'/);
    assert.match(taskApi, /searchParams\.set\('job_type'/);
    assert.match(taskDrawer, /nfc-prewrap-error/);
  });

  test('real desktop failed-row text passes opaque-painted AA in light/dark normal and hover', () => {
    const css = read('src/styles/console-v2-tasks.css');
    const paintColors = read('scripts/computed-paint-color.mjs');
    const paintTests = read('scripts/computed-paint-color.test.mjs');
    assert.match(taskPage, /className="nfc-table-error nfc-v2-task-error"/);
    assert.match(css, /\.nfc-v2-task-error\s*\{[^}]*color:\s*#c03c51;/s);
    assert.match(css, /\[data-theme='dark'\] \.nfc-v2-tasks-page \.nfc-v2-task-error\s*\{\s*color:\s*#ffbdc9;/);
    for (const marker of [
      "import { computedContrastRatio } from './computed-contrast.mjs'",
      'const errorPaintCases = []',
      'async function inspectTableErrorPaint(page, theme, width, state)',
      "expectedState === 'hover'",
      'row.matches',
      "style.backgroundImage !== 'none'",
      "style.filter !== 'none'",
      "parsed.alpha === 1",
      "import { parseComputedPaintColor, contrastRatioForOpaqueChannels } from './computed-paint-color.mjs'",
      'const fg = parseComputedPaintColor(snapshot.foreground)',
      'const parsed = parseComputedPaintColor(layer.color)',
      'contrastRatioForOpaqueChannels(fg.channels, composite)',
      'Math.min(exactContrast, roundedContrast)',
      'computedContrastRatio(rgb(fg.channels), rgb(composite))',
      'ratio >= 4.5',
      'await inspectTableErrorPaint(page, theme, width,',
      "await page.locator('.nfc-v2-task-table tbody tr .nfc-v2-task-error').first().hover()",
      'WIDTHS.filter(width => width >= 768).length * THEMES.length * 2',
      "task-table-error-paint-contrast-audit.json",
      '40/40 actual desktop normal/hover error text pairs',
    ]) assert.ok(browser.includes(marker), 'Missing fail-closed painted error gate: ' + marker);
    for (const marker of ["const OKLAB = new RegExp",
      "Out-of-gamut Oklab requires rendered pixel audit",
      "if (alpha === 0) return { channels: [0, 0, 0], alpha: 0 }",
      "contrastRatioForOpaqueChannels"])
      assert.ok(paintColors.includes(marker), 'Missing Oklab validation: ' + marker);
    assert.ok(paintTests.includes('canonical black, white, red and blue references'));
    for (const marker of ["url.origin !== BASE", "request.method() !== 'GET'",
      'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []'])
      assert.ok(browser.includes(marker), 'Missing browser isolation: ' + marker);
  });

  test('only localhost Vite with synthetic GET; failed API requests never become real mutations', () => {
    for (const token of [
      "url.origin !== BASE", "request.method() !== 'GET'",
      "status: 405", "fail ? 503 : 200",
      "JSON.stringify(fail", "fixture(url)",
      'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
      'await page.screenshot', 'await page.keyboard.press',
    ]) assert.ok(browser.includes(token), token);
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-task-ledger-states.mjs',
      'frontend/artifacts/browser-task-ledger-states/*.png',
      'frontend/artifacts/browser-task-ledger-states/task-table-error-paint-contrast-audit.json',
    ]) assert.ok(ci.includes(token), token);
    assert.doesNotMatch(browser, /(?:tasksApi|plansApi|quarantineApi)\.(?:delete|clearTaskHistory|purge|execute|freeze|validate)\(/);
  });
});
