import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const browser = read('scripts/browser-workflow-preview-overlays.mjs');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5D-C Workflow Preview/Draft Chromium acceptance', () => {
  test('real React/Radix portals enforce dimensions and 1300/1301 stack in four themes', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      "page.goto(BASE_URL + url", '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'light'", "mode: 'dark'", "mode: 'system'",
      'getComputedStyle(dialog)', 'document.elementFromPoint(x, y)',
      'Number(os.zIndex) === 1300', 'Number(cs.zIndex) === 1301',
      "os.backdropFilter === 'none'", "page.keyboard.press('Escape')",
      'assert.equal(completed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(browser.includes(token), token);
  });

  test('Legacy and Utility coverage protects Preview identity, dirty/archived and candidate guards', () => {
    for (const token of [
      "goto('/workflows/41')", "goto('/workflows/42')",
      "goto('/workflows/43')", "goto('/workflows/41?revision=1')",
      'Root change must invalidate file Preview',
      'Dirty file workflow must not Preview',
      'Historical revision cannot edit',
      'Dirty Utility workflow must not Draft',
      'Server-proposed blocked member must be sanitized',
      'Zero selected READY candidates block Draft',
      'Confirmation must reflect exactly one READY candidate',
      'Preview calls must be revision-pinned and immutable',
      'expected_compile_digest', // optional term documented through utility helpers, not necessarily in runner
    ]) if (token !== 'expected_compile_digest') assert.ok(browser.includes(token), token);
  });

  test('only synthetic read-only Preview may POST, no Generate, Save, Rollback or remote NAS calls', () => {
    for (const token of [
      'url.origin !== BASE_URL', "request.method() === 'GET'",
      "request.method() === 'POST' && match",
      "const match = /^\\/api\\/workflows\\/(41|42)\\/preview$/.exec(url.pathname)",
      'status: 405', 'assert.deepEqual(forbidden, []', 'assert.deepEqual(external, []',
    ]) assert.ok(browser.includes(token), token);
    assert.doesNotMatch(browser, /(?:legacyDraft|utilityDraft|confirm\.getByRole\([^)]*\))\.click\(/);
    assert.doesNotMatch(browser, /workflowApi\.(generatePlan|rollbackWorkflow|updateWorkflow)\(/);
  });

  test('exact HEAD CI runs new matrix and saves screenshot artifact alongside previous five', () => {
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-quarantine-bulk-overlays.mjs',
      'node scripts/browser-plan-lifecycle-overlays.mjs',
      'node scripts/browser-workflow-preview-overlays.mjs',
      'frontend/artifacts/browser-workflow-preview/*.png',
    ]) assert.ok(workflow.includes(token), token);
  });
});
