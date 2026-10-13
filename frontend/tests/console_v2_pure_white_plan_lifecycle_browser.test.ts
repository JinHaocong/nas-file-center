import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const runner = read('scripts/browser-plan-lifecycle-overlays.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5D-B Plan Lifecycle real Chromium evidence', () => {
  test('asserts genuine Radix dialog/sheet computed stacking at eight responsive sizes and four themes', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'light'", "mode: 'dark'", "mode: 'system'",
      "page.goto(BASE_URL + '/plans/' + id",
      'getComputedStyle(content)', 'document.elementFromPoint(x, y)',
      "kind === 'confirm' ? 1300 : 1100",
      "ms.backdropFilter === 'none'",
      "await page.keyboard.press('Escape')",
      'assert.equal(completed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(runner.includes(token), token);
  });

  test('checks eight plan status/authority variants without invoking dangerous actions', () => {
    for (const token of [
      "101: { status: 'draft' }", "102: { status: 'frozen' }",
      "103: { status: 'ready' }", "104: { status: 'stale', workflow: true }",
      "105: { status: 'ready', readOnly: true }",
      "106: { status: 'ready', activeJob: 700 }",
      "107: { status: 'completed' }", "108: { status: 'stale', dedupe: true }",
      'ALLOW_MUTATION=false must block Execute', 'Active worker blocks Execute',
      'Stale Plan must never expose Execute', 'Stale Dedupe requires rescan',
      'Confirm UI enabled but NEVER clicked', 'Journal must reveal original read-only evidence',
    ]) assert.ok(runner.includes(token), token);
  });

  test('only mocked read-only rebuild-preview POST is permitted and zero remote requests', () => {
    for (const token of [
      'url.origin !== BASE_URL', "request.method() === 'GET'",
      "request.method() === 'POST' && url.pathname === '/api/plans/104/rebuild-preview'",
      'status: 405', 'assert.deepEqual(forbidden, []', 'assert.deepEqual(external, []',
      'assert.equal(rebuildPreviews, 1',
    ]) assert.ok(runner.includes(token), token);
    assert.doesNotMatch(runner, /(?:safeExecute|generateDraft|confirmExecute|confirmUndo|confirm)\.click\(/);
    assert.doesNotMatch(runner, /plansApi\.(freezePlan|validatePlan|executePlan|createUndoPlan|deletePlan)\(/);
  });

  test('CI builds exact HEAD and captures all five browser scenario folders', () => {
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-quarantine-bulk-overlays.mjs',
      'node scripts/browser-plan-lifecycle-overlays.mjs',
      'frontend/artifacts/browser-plan-lifecycle/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
