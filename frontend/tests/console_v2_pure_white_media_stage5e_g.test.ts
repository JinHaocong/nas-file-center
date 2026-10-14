import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const browser = read('scripts/browser-media-ledger-states.mjs');
const page = read('src/pages/Media/index.tsx');
const domain = read('src/api/domain.ts');
const css = read('src/styles/console-v2-media.css');
const common = read('src/styles/console-v2.css');
const entry = read('src/main.tsx');
const ci = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5E-G Media complex-state browser acceptance', () => {
  test('7 real Media states cover 8 widths x 4 themes, with safety fences and reset', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "'VeryLongUnbrokenCameraArchiveFolder'.repeat(5)",
      "'LosslessMasterFilename'.repeat(6)",
      "name: '下一页'", "get('page') === '2'",
      "selectOption('video')", "selectOption('corrupt')",
      "selectOption('changed')", "get('page') === '1'",
      "get('verification_status') === 'changed'",
      'NeverExistsMediaFixtureToken',
      "name: '分析媒体', exact: true",
      "name: 'SHA256 校验', exact: true",
      'Blocked root must remain disabled',
      'New verify dialog must not inherit analyze selection',
      'Healthy media must not be selectable',
      'Unknown media must never be selectable',
      'Media filter bar overflow', 'Media search overflow',
      'Media desktop scrollport overflow', 'Media long-path card overflow',
      'Media GET 503 error alert overflow',
      'media dialog z-index', 'dialog pointer hit',
      "'dense-media-' + label", "'media-page-two-' + label",
      "'media-compound-filters-' + label",
      "'media-empty-search-' + label",
      "'media-analyze-dialog-' + label",
      "'media-verify-dialog-' + label",
      "'media-list-503-' + label",
      '32/32 cases, 224 screenshots',
    ]) assert.ok(browser.includes(token), token);
    assert.match(page, /const canSelect = \(record: MediaAsset\)/);
    assert.match(page, /record\.integrity_status === 'corrupt' && record\.can_direct_delete/);
    assert.match(page, /const changePage = \(nextPage/);
    assert.match(page, /setSearchApplied\(search\.trim\(\)\); setPage\(1\); resetSelection\(\)/);
    assert.match(page, /change\(\); setPage\(1\); resetSelection\(\)/);
    assert.match(page, /<QueueDialog kind="analyze"/);
    assert.match(page, /<QueueDialog kind="verify"/);
    assert.match(domain, /query\.set\('verification_status'/);
    assert.match(domain, /query\.set\('media_kind'/);
    assert.match(domain, /query\.set\('search'/);
  });

  test('specific Media Radix content overrides generic dialog z-index below its scrim', () => {
    assert.match(common, /\.nfc-v2-dialog\[data-state='open'\][\s\S]*?z-index:\s*1101/);
    assert.match(css, /\.nfc-v2-media-queue-dialog\[data-state='open'\]\s*\{\s*z-index:\s*1301\s*;/);
    assert.match(entry, /import '\.\/styles\/console-v2-media\.css'/);
    for (const token of [
      'status: 405', "request.method() !== 'GET'",
      'url.origin !== BASE', 'fail ? 503 : 200',
      'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
      'await page.keyboard.press', 'assert.equal(passed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(browser.includes(token), token);
    assert.doesNotMatch(browser, /(?:mediaApi|plansApi|indexesApi)\.(?:analyze|verifyIntegrity|previewCorruptDelete|createCorruptDeletePlan|executePlan|deleteIndex)\(/);
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-media-ledger-states.mjs',
      'frontend/artifacts/browser-media-ledger-states/*.png',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-task-ledger-states.mjs',
    ]) assert.ok(ci.includes(token), token);
  });
});
