import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (name: string) => readFileSync(resolve(process.cwd(), name), 'utf8');
const source = read('scripts/browser-organizer-dedupe-overlays.mjs');
const ci = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5D-D read-only Organizer/Dedupe real Chromium acceptance', () => {
  test('uses actual built React/Radix portals at eight widths and four themes', () => {
    for (const token of [
      "import { chromium } from 'playwright'",
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'light'", "mode: 'dark'", "mode: 'system'",
      'getComputedStyle(dialog)', 'document.elementFromPoint(x, y)',
      'Number(ms.zIndex) === 1300', 'Number(cs.zIndex) === 1301',
      "ms.backdropFilter === 'none'",
      "page.keyboard.press('Escape')",
      'assert.equal(completed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(source.includes(token), token);
  });

  test('Stage 5E-AP waits for actual Radix pointer hit before enforcing stacking contract', () => {
    // A visible portal can precede the browser's pointer-hit update by a
    // frame. The wait is bounded and cannot suppress a truly blocked dialog.
    for (const token of [
      'await page.waitForFunction(() => {',
      "polling: 'raf', timeout: 2000",
      'document.elementFromPoint(x, y)',
      "const problems = await page.evaluate",
      "assert.deepEqual(problems, [], label + ' ' + problems.join('; '))",
    ]) assert.ok(source.includes(token), token);
    assert.match(source, /async function assertConfirm\([\s\S]*?await page\.waitForFunction\([\s\S]*?const problems = await page\.evaluate/);
    assert.doesNotMatch(source, /polling:\s*'raf',\s*timeout:\s*2000\s*}\)\.catch\(/,
      'A timed-out pointer-hit wait must fail CI instead of being ignored');
  });

  test('Organizer Advanced keeps conflict, missing digest, Stage A/B barriers', () => {
    for (const token of [
      'Organizer Preview 存在 1 个 blocking conflict',
      'Conflicts must block Stage B Draft',
      'Structural Stage A must visibly lock Stage B work',
      'Stage A 执行完成后必须重新 Preview',
      'Missing preview_digest must block Stage B Draft',
      'Organizer Stage A', 'Organizer Stage B',
      'organizer-conflict-', 'organizer-stage-a-', 'organizer-stage-b-',
    ]) assert.ok(source.includes(token), token);
  });

  test('Dedupe requires completed Scan and an authoritative summary, and revokes stale identity', () => {
    for (const token of [
      'No completed Scan selected => Preview disabled',
      "picker.locator('option[value=\"503\"]')",
      'Missing dedupe_summary blocks Draft',
      '第 r2 版', 'Scan #501',
      'Dedupe safety identity must disclose Protect Last File',
      'Changing completed Scan identity revokes old Preview/Draft',
      'Old Scan authority must disappear',
      'All Preview responses must pin exact Workflow revision and Scan authority',
    ]) assert.ok(source.includes(token), token);
  });

  test('GET fixtures and only locally fulfilled Preview POST are allowed: no NAS or mutation', () => {
    for (const token of [
      'url.origin !== BASE_URL', "request.method() === 'GET'",
      'const previewMatch = /^\\/api\\/workflows\\/(51|52)\\/preview$/.exec(url.pathname)',
      "request.method() === 'POST' && previewMatch",
      'status: 405', 'assert.deepEqual(forbidden, []', 'assert.deepEqual(external, []',
    ]) assert.ok(source.includes(token), token);
    assert.doesNotMatch(source, /confirm\.getByRole\([^)]*\)\.click\(/);
    assert.doesNotMatch(source, /workflowApi\.(generatePlan|rollbackWorkflow|updateWorkflow)\(/);
  });

  test('exact-HEAD CI includes this new browser runner and sixth preceding matrices', () => {
    for (const token of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-quarantine-bulk-overlays.mjs',
      'node scripts/browser-plan-lifecycle-overlays.mjs',
      'node scripts/browser-workflow-preview-overlays.mjs',
      'node scripts/browser-organizer-dedupe-overlays.mjs',
      'frontend/artifacts/browser-organizer-dedupe/*.png',
    ]) assert.ok(ci.includes(token), token);
  });
});
