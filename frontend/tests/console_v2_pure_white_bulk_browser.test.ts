import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const runner = read('scripts/browser-quarantine-bulk-overlays.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5D-A real Chromium Quarantine bulk acceptance', () => {
  test('checks real React/Radix overlays across 8 widths and 4 effective themes', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'light'", "mode: 'dark'", "mode: 'system'",
      "page.goto(BASE_URL + '/quarantine'",
      'getComputedStyle(dialog)', 'document.elementFromPoint(x, y)',
      'Number(os.zIndex) === 1300', 'Number(ds.zIndex) === 1301',
      "os.backdropFilter === 'none'", "await page.keyboard.press('Escape')",
      'assert.equal(completed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(runner.includes(token), token);
  });

  test('exercises selected-only, policy invalidation, fail-closed blocked Preview and DELETE', () => {
    for (const token of [
      '选择本页 active (2)', 'Only skip and rename allowed',
      'Policy change invalidates Preview', 'VISUAL_FIXTURE_BLOCKED',
      'Any blocked restore member must prevent whole Draft',
      'Blocked second Preview must revoke both digest and DELETE',
      "'delete', 'DELETE ', ' Delete'", "await token.fill('DELETE')",
      'hard link', '独立副本', 'preview_digest', 'assert.deepEqual(previewCalls',
    ]) assert.ok(runner.includes(token), token);
  });

  test('only synthetic bulk-preview POST is fulfilled; no Draft/Execute, external API or NAS', () => {
    assert.ok(runner.includes("url.origin !== BASE_URL"));
    assert.ok(runner.includes("request.method() === 'GET'"));
    assert.ok(runner.includes("request.method() === 'POST' && url.pathname === '/api/quarantine/bulk-preview'"));
    assert.ok(runner.includes('status: 405'));
    assert.ok(runner.includes('assert.deepEqual(forbidden, []'));
    assert.ok(runner.includes('assert.deepEqual(external, []'));
    assert.doesNotMatch(runner, /(?:generateRestore|generatePurge)\.click\(/);
    assert.doesNotMatch(runner, /quarantineApi\.(bulkPlan|purge|restore)\(/);
  });

  test('exact-HEAD CI includes all four screenshot folders and the new matrix', () => {
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-quarantine-bulk-overlays.mjs',
      'frontend/artifacts/browser-quarantine-bulk/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
