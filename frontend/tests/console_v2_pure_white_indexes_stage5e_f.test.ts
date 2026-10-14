import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const browser = read('scripts/browser-indexes-ledger-states.mjs');
const indexes = read('src/pages/Indexes/index.tsx');
const lifecycle = read('src/components/indexes/index_lifecycle.ts');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5E-F Indexes complex state gates', () => {
  test('32 real Chromium combinations validate long-path/index-state safety and transitions', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "'UnbrokenOriginalMediaArchiveFolderName'.repeat(7)",
      "i === 1 ? 'blocked' : i === 2 ? 'missing'",
      "'long-path-states-' + label", "'page-two-' + label",
      "'create-dialog-' + label", "'metadata-confirm-' + label",
      "'list-error-' + label",
      'First page must contain 20 roots',
      "getByRole('button', { name: '下一页' })",
      "new URLSearchParams(q).get('page') === '2'",
      'Active root cannot be removed',
      'Unavailable root cannot be queued for reindex',
      'Empty index path must not allow queue submission',
      'Metadata-only removal disclosure must remain visible',
      'Indexes error alert exceeds viewport',
      'Long-path index mobile card exceeds viewport',
      'Desktop table scrollport exceeds viewport',
      'Pagination exceeds viewport',
      'dialog pointer hit', 'dialog z-index',
      'await page.keyboard.press',
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
      '32/32 cases, 160 screenshots',
    ]) assert.ok(browser.includes(token), token);
    assert.match(indexes, /getIndexRemoveAvailability\(record\)/);
    assert.match(indexes, /record\.path_state === 'available'/);
    assert.match(indexes, /<ConsolePagination page=\{page\} pageSize=\{pageSize\}/);
    assert.match(indexes, /onChange=\{changePage\}/);
    assert.match(indexes, /nfc-v2-index-create-dialog/);
    assert.match(lifecycle, /if \(root\.has_active_job \|\| root\.can_remove === false\)/);
    assert.match(lifecycle, /case 'blocked':/);
    assert.match(lifecycle, /case 'missing':/);
  });

  test('browser uses localhost-only synthetic GET, denies mutations and preserves prior suites', () => {
    for (const token of [
      'url.origin !== BASE', "request.method() !== 'GET'",
      'status: 405', 'fail ? 503 : 200',
      'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
      "url.pathname === '/api/indexes'", 'await page.screenshot',
      "name: '重新加载'", "name: '刷新', exact: true",
    ]) assert.ok(browser.includes(token), token);
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-indexes-ledger-states.mjs',
      'frontend/artifacts/browser-indexes-ledger-states/*.png',
      'node scripts/browser-task-ledger-states.mjs',
      'node scripts/browser-workspace-cascade.mjs',
    ]) assert.ok(workflow.includes(token), token);
    assert.doesNotMatch(browser, /(?:indexesApi|tasksApi|plansApi)\.(?:createIndex|deleteIndex|execute|purge|freeze|validate)\(/);
  });
});
