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
      '32/32 cases, 128 screenshots',
    ]) assert.ok(browser.includes(token), token);
    assert.match(taskPage, /setPage\(1\)/);
    assert.match(taskPage, /isError\s*\?\s*\(/);
    assert.match(taskPage, /<TaskDetailDrawer/);
    assert.match(taskApi, /searchParams\.set\('page_size'/);
    assert.match(taskApi, /searchParams\.set\('status'/);
    assert.match(taskApi, /searchParams\.set\('job_type'/);
    assert.match(taskDrawer, /nfc-prewrap-error/);
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
    ]) assert.ok(ci.includes(token), token);
    assert.doesNotMatch(browser, /(?:tasksApi|plansApi|quarantineApi)\.(?:delete|clearTaskHistory|purge|execute|freeze|validate)\(/);
  });
});
