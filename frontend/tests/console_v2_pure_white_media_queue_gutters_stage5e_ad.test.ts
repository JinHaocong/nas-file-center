import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const page = read('src/pages/Media/index.tsx');
const css = read('src/styles/console-v2-media.css');
const browser = read('scripts/browser-media-ledger-states.mjs');

describe('Pure White Stage 5E-AD media queue screenshot-led spacing and path disclosure', () => {
  test('Media body owns title-aligned desktop/mobile gutters and accessible long-root disclosure', () => {
    for (const token of [
      'padding:18px 24px 16px;',
      '.nfc-v2-media-queue-body { padding:16px 18px 14px; }',
      '.nfc-v2-media-root-option {',
      '.nfc-v2-media-root-path {',
      '-webkit-line-clamp:2',
      '.nfc-v2-media-root-reveal summary:focus-visible',
      'overflow-wrap:anywhere;white-space:pre-wrap',
    ]) assert.ok(css.includes(token), token);
    for (const token of [
      '<div className="nfc-v2-media-root-option" key={option.value}>',
      'option.label.length > 96',
      '<details className="nfc-v2-media-root-reveal">',
      '<summary>查看完整路径</summary>',
      '<p>{option.label}</p>',
      '<span className="nfc-v2-media-root-path">{option.label}</span>',
      'disabled={option.disabled}',
      'roots.filter(value => value !== option.value)',
      "root.path_state !== 'available'",
      '!options.some(option => option.value === root && !option.disabled)',
    ]) assert.ok(page.includes(token), token);
    assert.ok(page.indexOf('</label>') < page.indexOf('<details className="nfc-v2-media-root-reveal">'),
      'Expanded path control must not nest inside checkbox label');
  });

  test('32-case genuine Chromium checks safe gutters, short options, full path and Enter without selecting blocked roots', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "state === 'analyze-expanded'",
      'const gutter = width < 768 ? 16 : 22;',
      'box.left >= rect.left + gutter',
      'box.right <= rect.right - gutter',
      'bounds.height <= 110',
      "css.webkitLineClamp === '2'",
      'full.textContent === preview?.textContent',
      "'media-expanded-root-' + label",
      "await fullPath.locator('summary').focus();",
      "await page.keyboard.press('Enter');",
      'await fullPath.locator(\'p\').innerText(), ROOT',
      'await options.nth(1).isDisabled(), true',
      '32/32 cases, 256 screenshots',
      "request.method() !== 'GET'",
      'status: 405',
      'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
    ]) assert.ok(browser.includes(token), token);
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(workflow.includes('node scripts/browser-media-ledger-states.mjs'));
    assert.ok(workflow.includes('Install and verify Chinese screenshot fonts'));
  });

  test('incremental shared mock migration keeps Media locked and cannot enable NAS writes', () => {
    const shared = read('scripts/visual-fixtures.mjs');
    for (const token of [
      'visualAdminFixture(username)', 'visualSafeSettingsFixture()',
      'allow_mutation: false', 'allow_delete: false', 'safe_mode: true',
    ]) assert.ok(shared.includes(token), token);
    for (const token of [
      "from './visual-fixtures.mjs'",
      "visualAdminFixture('media-readonly-visual-fixture')",
      'visualSafeSettingsFixture()',
      'url.origin !== BASE',
      "request.method() !== 'GET'",
      'status: 405',
    ]) assert.ok(browser.includes(token), token);
    assert.doesNotMatch(browser, /(?:mediaApi|plansApi|indexesApi)\.(?:analyze|verifyIntegrity|executePlan|deleteIndex)\(/);
  });
});
