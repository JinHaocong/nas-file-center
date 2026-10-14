import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const css = read('src/styles/v049-workspace.css');
const browser = read('scripts/browser-workspace-cascade.mjs');
const ci = read('../.github/workflows/ui-v044-validation.yml');

function blocks(selector: string): string[] {
  const escaped = selector.replace(/[.*+?^$\x7b\x7d()|[\]\\]/g, '\\$&');
  return [...css.matchAll(new RegExp('(?:^|\\n)' + escaped + '\\s*\\{([^}]*)\\}', 'g'))]
    .map(match => match[1]);
}

describe('Pure White Stage 5E-D Media / Quarantine dense-status acceptance', () => {
  test('retire exactly 12 redundant v049 declarations with later equal-importance winners', () => {
    const retired: Array<[string, string[]]> = [
      ['.nfc-data-panel-dense', ['border-radius']],
      ['.nfc-data-panel-quiet', ['border-color', 'background']],
      ['.nfc-overlay-section', ['border-color', 'border-radius', 'background']],
      ['.nfc-overlay-section-header', ['min-height', 'padding', 'border-bottom-color', 'background']],
      ['.nfc-directory-picker-body', ['gap']],
      ['.nfc-mobile-pagination', ['background']],
    ];
    let removed = 0;
    for (const [selector, properties] of retired) {
      const declarations = blocks(selector);
      assert.equal(declarations.length, 2, selector + ' requires later authoritative rule');
      for (const property of properties) {
        const escaped = property.replace(/[-]/g, '\\-');
        const pattern = new RegExp('(?:^|\\n)\\s*' + escaped + '\\s*:', 'm');
        assert.doesNotMatch(declarations[0], pattern,
          selector + ' must not retain the old ' + property);
        assert.match(declarations[1], pattern,
          selector + ' must retain the effective ' + property);
        removed++;
      }
    }
    assert.equal(removed, 12);
    assert.match(blocks('.nfc-data-panel-quiet')[0], /box-shadow:\s*none\s*!important/);
    assert.match(blocks('.nfc-overlay-section-header')[1], /min-height:\s*54px/);
  });

  test('populate real Media and Quarantine with complete authority/status fixtures', () => {
    for (const token of [
      "path: '/media', id: 'media'", "path: '/quarantine', id: 'quarantine'",
      '.nfc-v2-media-table tbody tr', '.nfc-v2-media-mobile .nfc-index-mobile-card',
      '.nfc-v2-media-table-scroll', '.nfc-v2-quarantine-table tbody tr',
      '.nfc-quarantine-mobile-card', '.nfc-v2-quarantine-table-scroll',
      "'healthy', 'verified', false", "'corrupt', 'changed', true",
      "'unknown', 'unverified', false",
      "'active'", "'conflict'", "'restored'",
      'HASH_MISMATCH_FROZEN_EVIDENCE', 'SAFE_PATH_CONFLICT',
      'Only corrupt frozen-evidence media #802 may be selected for delete Preview',
      'Only active quarantine entry #901 may be selected',
      'Media badge missing', 'Quarantine state missing',
      'getComputedStyle(scroll).overflowX',
      'Mobile dense card exceeds viewport bounds',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(browser.includes(token), token);
  });

  test('all 11 pages use local synthetic GET only with no destructive API submission', () => {
    for (const token of [
      "request.method() !== 'GET'", 'url.origin !== BASE',
      'status: 405', 'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []', "let denseMode = false",
      'await inspectDense(page, item, width)',
      'await page.screenshot',
      'assert.equal(passed, WIDTHS.length * THEMES.length)',
    ]) assert.ok(browser.includes(token), token);
    for (const item of [
      'node scripts/browser-workspace-cascade.mjs',
      'frontend/artifacts/browser-workspace-cascade/*.png',
      'Checkout exact candidate HEAD', 'Verify candidate identity',
    ]) assert.ok(ci.includes(item), item);
    assert.doesNotMatch(browser, /(?:mediaApi|quarantineApi|plansApi)\.(?:purge|delete|execute|freeze|validate|analyze|verifyIntegrity)\(/);
  });
});
